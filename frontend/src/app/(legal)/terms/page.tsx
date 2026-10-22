import type { Metadata } from "next";
import Link from "next/link";

import { LegalHeader } from "../_components";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "The agreement between you and VerifyGH.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <>
      <LegalHeader
        title="Terms of Service"
        updated="30 September 2026"
        summary="You top up a wallet with Mobile Money and spend it on verification numbers we buy from an authorised provider on your behalf. Prices are in cedis and shown before you pay. If we cannot deliver, you get your money back automatically. You are responsible for how you use the numbers."
      />

      <h2>1. Who we are</h2>
      <p>
        VerifyGH (&quot;we&quot;, &quot;us&quot;) operates a payment and access platform that lets
        customers in Ghana purchase phone verification services, supplied by an authorised
        third-party provider, using Ghanaian Mobile Money.
      </p>
      <p>
        We are not affiliated with, endorsed by, or acting on behalf of any of the platforms a
        verification number may be used with.
      </p>

      <h2>2. Your account</h2>
      <ul>
        <li>You must be at least 18 years old and legally able to enter into this agreement.</li>
        <li>You must give accurate details and keep them up to date.</li>
        <li>
          You are responsible for everything done through your account. Keep your password secret
          and tell us immediately at{" "}
          <a href="mailto:support@getverifygh.com">support@getverifygh.com</a> if you think
          someone else has access.
        </li>
        <li>One person, one account. Accounts may not be shared, sold or transferred.</li>
        <li>
          We may require you to confirm your email address before you can make a purchase.
        </li>
      </ul>

      <h2>3. Your wallet</h2>
      <p>
        Money you add to VerifyGH is held as a prepaid balance denominated in Ghana Cedis (GHS) and
        is used only to purchase services on this platform.
      </p>
      <ul>
        <li>Your balance is not a bank deposit and does not earn interest.</li>
        <li>
          A deposit is credited only after our payment provider confirms it to us directly. Until
          that confirmation arrives, a payment is pending.
        </li>
        <li>
          Every movement of money is recorded as an immutable ledger entry with a reference, which
          you can see in your transaction history.
        </li>
        <li>
          Deposit amounts, maximum balance and daily spending are subject to limits shown in the
          app. We may adjust these to manage risk.
        </li>
      </ul>

      <h2>4. Prices and payment</h2>
      <ul>
        <li>
          Prices are quoted in cedis and shown in full before you confirm. The price includes the
          currency conversion, our margin and the Mobile Money collection fee.
        </li>
        <li>
          The price is fixed at the moment you confirm the purchase, and is recorded on the order
          together with the exchange rate used. A later rate change does not affect a completed
          order.
        </li>
        <li>
          Prices and availability change with our provider&apos;s costs and stock. A price shown
          earlier in a session is not a guarantee.
        </li>
        <li>
          You authorise us to deduct the confirmed price from your wallet balance when you place an
          order.
        </li>
      </ul>

      <h2>5. Orders and delivery</h2>
      <p>
        When you place an order we reserve a number from our provider on your behalf. The number is
        reserved for a limited period, shown on your order screen with a countdown.
      </p>
      <ul>
        <li>
          We do not guarantee that a particular platform will accept a particular number, or that a
          verification message will arrive. That depends on the platform you are verifying with.
        </li>
        <li>
          Where our provider agreement permits it, the verification code is shown on your order
          screen. Where it does not, we show delivery status only.
        </li>
        <li>
          A number is for a single verification. Do not treat it as a number you control or can
          rely on afterwards.
        </li>
        <li>
          Numbers come from our provider&apos;s shared pool and are reissued over time. We do not
          guarantee that a number has never been used with a particular service before, and
          neither we nor our provider can check a number&apos;s history with another service in
          advance.
        </li>
      </ul>

      <h2>6. Refunds</h2>
      <p>Refunds are automatic and go back to your VerifyGH wallet. Our policy is:</p>
      <ul>
        <li>
          <strong>Provider could not supply a number:</strong> full refund, automatically.
        </li>
        <li>
          <strong>Number expired with no verification code received:</strong> full refund,
          automatically.
        </li>
        <li>
          <strong>You cancelled before a code arrived:</strong> full refund, automatically.
        </li>
        <li>
          <strong>A verification code was delivered:</strong> the service was provided, so no
          automatic refund applies.
        </li>
        <li>
          <strong>The number could not be used because the service treated it as already
          registered (or rejected it):</strong> report it from your order screen within the time
          shown there. We review every report; where we confirm the number was unusable for the
          service you bought it for, we give you a replacement number or refund the order to your
          wallet. A report is not an automatic refund.
        </li>
      </ul>
      <p>
        If something went wrong outside these cases, contact support with your order reference. We
        review disputes individually. Wallet balances are not generally withdrawable to Mobile
        Money; where we do return a balance (for example on account closure), we return it through
        the channel it came from.
      </p>

      <h2>7. Acceptable use</h2>
      <p>
        Your use of VerifyGH is governed by our{" "}
        <Link href="/acceptable-use">Acceptable Use Policy</Link>, which forms part of these terms.
        In particular, VerifyGH must not be used for fraud, impersonation, spam, evading bans or
        platform security, or circumventing identity or KYC checks.
      </p>
      <p>
        You are responsible for complying with the terms of any third-party service you use a
        number with. If that service prohibits verification numbers, do not use ours with it.
      </p>

      <h2>8. Suspension and closure</h2>
      <p>
        We may limit, suspend or close an account that breaches these terms or our Acceptable Use
        Policy, that we are legally required to act on, or that presents a serious risk of harm or
        fraud. Where we do, we record the reason and will share it with you on request unless the
        law prevents us.
      </p>
      <p>You may close your account at any time by contacting support.</p>

      <h2>9. Availability</h2>
      <p>
        We work to keep VerifyGH available, but we do not guarantee uninterrupted service. We may
        suspend access for maintenance, or where our provider or payment partner is unavailable.
      </p>

      <h2>10. Liability</h2>
      <p>
        To the extent permitted by Ghanaian law, our total liability to you for any claim arising
        out of your use of VerifyGH is limited to the amount you paid us for the order the claim
        relates to. We are not liable for indirect or consequential loss, for loss of profits, or
        for the acts of any third-party platform you verify with.
      </p>
      <p>Nothing in these terms limits liability that cannot be limited by law.</p>

      <h2>11. Changes to these terms</h2>
      <p>
        We may update these terms. If a change is material we will ask you to accept the new
        version before your next purchase. The version you accepted is recorded on your account.
      </p>

      <h2>12. Governing law</h2>
      <p>
        These terms are governed by the laws of the Republic of Ghana, and the courts of Ghana have
        exclusive jurisdiction over any dispute.
      </p>

      <h2>13. Contact</h2>
      <p>
        <a href="mailto:support@getverifygh.com">support@getverifygh.com</a>
      </p>
    </>
  );
}
