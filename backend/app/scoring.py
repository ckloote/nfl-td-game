"""Touchdown credits and pick scores.

Ported from the selector (`../nfl-player-selector/src/pool/scoring.py` and `results.py`),
which is the reference for the pool's scoring rule:

- Every touchdown counts for its scorer, including returns, recoveries and laterals.
- A passing touchdown also counts for the passer.
- Two-point conversions, extra-point plays and negated plays count for nobody.

A game's touchdowns are trusted only when the play-by-play has an end-of-game marker,
its final score equals the schedule's, and every credited touchdown names a player.
Until then a pick in that game is *pending*, never zero.

Nothing here stores a pick's score: it is computed from the credits whenever it is asked
for, so an upstream stat correction shows up after the next refresh.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Game, GameResult, Pick, TouchdownCredit

PBP_REQUIRED = {
    "game_id",
    "play_id",
    "touchdown",
    "pass_touchdown",
    "td_player_id",
    "passer_player_id",
    "two_point_attempt",
    "extra_point_attempt",
    "play_type",
    "desc",
    "total_home_score",
    "total_away_score",
}
PBP_OPTIONAL = {"no_play", "game_end", "td_team", "td_player_name", "passer_player_name", "posteam"}
FLAGS = ("touchdown", "pass_touchdown", "two_point_attempt", "extra_point_attempt")
END_OF_GAME = re.compile(r"\bEND (?:OF )?GAME\b", re.IGNORECASE)


def _num(value):
    """None for missing (null or NaN); integral floats become ints so 1 == 1.0."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _is(row: dict, column: str) -> bool:
    return _num(row.get(column)) == 1


def transform_touchdowns(
    rows: list[dict], schedule: dict[str, tuple[int | None, int | None]]
) -> tuple[list[dict], list[dict]]:
    """Play-by-play rows -> (touchdown credits, one completeness result per game).

    `schedule` maps game_id to the schedule's (home_score, away_score); games outside it
    (postseason, other seasons) are ignored. `td_player_id` is authoritative even on
    returns, recoveries and laterals.
    """
    if rows:
        missing = PBP_REQUIRED - set(rows[0])
        if missing:
            raise ValueError(f"play-by-play missing required columns: {sorted(missing)}")
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("game_id") is None or _num(row.get("play_id")) is None:
            raise ValueError("play-by-play contains unresolved game/play identifiers")
        for flag in FLAGS:
            if _num(row[flag]) not in (None, 0, 1):
                raise ValueError(f"invalid {flag} flags in play-by-play")
        by_game[row["game_id"]].append(row)

    credits: dict[tuple, dict] = {}
    results = []
    for game_id, raw in by_game.items():
        if game_id not in schedule:
            continue
        compared = sorted(PBP_REQUIRED | ({"no_play", "td_team"} & set(raw[0])))
        versions: dict[int, set[tuple]] = defaultdict(set)
        latest: dict[int, dict] = {}
        for row in raw:
            play_id = int(_num(row["play_id"]))
            versions[play_id].add(tuple(_num(row.get(c)) for c in compared))
            latest[play_id] = row
        conflict = any(len(v) > 1 for v in versions.values())
        plays = [latest[play_id] for play_id in sorted(latest)]

        unresolved = False
        for play in plays:
            conversion = _is(play, "two_point_attempt") or _is(play, "extra_point_attempt")
            negated = play.get("play_type") == "no_play" or _is(play, "no_play")
            if not _is(play, "touchdown") or conversion or negated:
                continue
            kinds = [("scoring", "td_player_id", "td_player_name", "td_team")]
            if _is(play, "pass_touchdown"):
                kinds.append(("throwing", "passer_player_id", "passer_player_name", "posteam"))
            for kind, id_col, name_col, team_col in kinds:
                player_id = play.get(id_col)
                if player_id is None or not str(player_id).strip():
                    unresolved = True
                    continue
                key = (game_id, int(_num(play["play_id"])), str(player_id), kind)
                credits[key] = dict(
                    game_id=key[0], play_id=key[1], player_id=key[2], kind=kind,
                    player_name=play.get(name_col), team=play.get(team_col),
                )

        # Play ids identify plays, not their order: a late-inserted timeout can have a
        # larger id than END GAME. Only explicit terminal markers give the final score.
        endings = [
            p for p in plays if END_OF_GAME.search(p.get("desc") or "") or _is(p, "game_end")
        ]
        finals = {(_num(p["total_home_score"]), _num(p["total_away_score"])) for p in endings}
        home, away = next(iter(finals)) if len(finals) == 1 else (None, None)
        expected = schedule[game_id]
        matches = None not in (home, away, *expected) and (home, away) == expected

        reasons = []
        if conflict:
            reasons.append("conflicting duplicate plays")
        if not endings:
            reasons.append("no end-of-game marker")
        if endings and not matches:
            reasons.append("terminal scores do not match schedule")
        if unresolved:
            reasons.append("touchdown identities unresolved")
        results.append(
            dict(
                game_id=game_id, complete=not reasons, reason="; ".join(reasons) or "complete",
                home_score=home, away_score=away,
            )
        )
    return list(credits.values()), results


# --- reading scores -----------------------------------------------------------
@dataclass(frozen=True)
class Board:
    """Everything needed to score any pick in a season, read once."""

    games: dict[str, Game]
    pending: dict[str, str]  # game_id -> why its touchdowns can't be trusted yet
    credits: dict[tuple[str, str], int]  # (game_id, player_id) -> touchdowns
    scored_in: dict[tuple[int, str], str]  # (week, player_id) -> game he has credits in

    def week_is_final(self, week: int) -> bool:
        games = [g for g in self.games.values() if g.week == week]
        return bool(games) and all(g.game_id not in self.pending for g in games)

    def final_through(self) -> int:
        """Last week in the unbroken run of final weeks starting at week 1; 0 if none."""
        week = 0
        while self.week_is_final(week + 1):
            week += 1
        return week


def load_board(db: Session, season: int) -> Board:
    games = {g.game_id: g for g in db.scalars(select(Game).where(Game.season == season))}
    results = {r.game_id: r for r in db.scalars(select(GameResult).where(GameResult.season == season))}
    pending = {}
    for game_id, game in games.items():
        result = results.get(game_id)
        if result is None:
            pending[game_id] = "not final yet"
        elif not result.complete:
            pending[game_id] = result.reason
        # Rechecked on every read, so a schedule correction un-finalizes old coverage.
        elif None in (game.home_score, game.away_score) or (
            result.home_score,
            result.away_score,
        ) != (game.home_score, game.away_score):
            pending[game_id] = "terminal scores do not match schedule"
    credits = {
        (game_id, player_id): count
        for game_id, player_id, count in db.execute(
            select(TouchdownCredit.game_id, TouchdownCredit.player_id, func.count())
            .where(TouchdownCredit.season == season)
            .group_by(TouchdownCredit.game_id, TouchdownCredit.player_id)
        )
    }
    scored_in = {(games[g].week, p): g for (g, p) in credits if g in games}
    return Board(games, pending, credits, scored_in)


def score_pick(board: Board, pick: Pick) -> tuple[int | None, str | None]:
    """(touchdowns, None) once final, else (None, why it is still pending).

    Scored from the game the player actually has credits in that week when there is one
    (he may have changed teams after the pick was made), otherwise the game he was
    picked in. A final game with no credits for him is a real zero.
    """
    game_id = board.scored_in.get((pick.week, pick.player_id), pick.game_id)
    if game_id in board.pending:
        return None, board.pending[game_id]
    return board.credits.get((game_id, pick.player_id), 0), None
