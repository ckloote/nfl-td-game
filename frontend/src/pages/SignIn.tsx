export default function SignIn() {
  const failed = new URLSearchParams(window.location.search).has("login_error");

  return (
    <main className="min-h-screen grid place-items-center bg-slate-50 p-6">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
        <h1 className="text-xl font-semibold text-slate-900">TD Pool</h1>
        <p className="mt-1 text-sm text-slate-500">Sign in with your Google account to make picks.</p>

        {failed && (
          <p role="alert" className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-700">
            Sign-in didn&apos;t complete. Please try again.
          </p>
        )}

        {/* A plain link: the whole OAuth dance is a full-page redirect handled by the
            backend. Swap this for Google's official sign-in button assets/branding
            before launch: https://developers.google.com/identity/branding-guidelines */}
        <a
          href="/api/auth/google/login"
          className="mt-6 flex w-full items-center justify-center rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          Sign in with Google
        </a>
      </div>
    </main>
  );
}
