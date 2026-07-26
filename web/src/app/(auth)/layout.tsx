import Link from "next/link";

/**
 * Shell for the unauthenticated auth screens.
 *
 * A centred single column with no navigation: on a sign-in page every extra link
 * is a way to not sign in.
 */
export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-md space-y-8">
        <div className="flex flex-col items-center gap-2">
          <Link
            href="/"
            className="text-2xl font-bold tracking-tight text-primary"
            aria-label="MedLMS home"
          >
            MedLMS
          </Link>
          <p className="text-sm text-muted-foreground">Medical education, done properly.</p>
        </div>
        {children}
      </div>
    </main>
  );
}
