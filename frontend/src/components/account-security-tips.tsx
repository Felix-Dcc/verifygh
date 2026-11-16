/** Once a code is in: keep the new account after this number is gone. */
const TIPS: Record<string, { title: string; steps: string[] }> = {
  whatsapp: {
    title: "Secure your new WhatsApp account",
    steps: [
      "Add a passkey: Settings → Account → Passkeys.",
      "Add your email: Settings → Account → Email address.",
      "Turn on two-step verification (2FA): Settings → Account → Two-step verification, and choose a 6-digit PIN. This PIN is your WhatsApp password, so write it down somewhere safe.",
    ],
  },
};

export function AccountSecurityTips({ slug, intro }: { slug: string; intro: string }) {
  const tips = TIPS[slug];
  if (!tips) return null;
  return (
    <div className="border-t border-line bg-sunken px-5 py-4 sm:px-6">
      <p className="text-sm font-medium text-ink">{tips.title}</p>
      <p className="mt-1 text-sm text-ink-soft">{intro}</p>
      <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm text-ink-soft">
        {tips.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
    </div>
  );
}
