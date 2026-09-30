import type { Metadata } from "next";
import Link from "next/link";

import { LegalHeader } from "../_components";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "What VerifyGH collects, why, and what we do not collect.",
};

export default function PrivacyPage() {
  return (
    <>
      <LegalHeader
        title="Privacy Policy"
        updated="30 September 2026"
        summary="We collect what a payment, an order and a support conversation actually need - and not more. We never see your Mobile Money PIN, we never sell your data, and verification codes are never written to our logs."
      />

      <h2>1. What we collect</h2>

      <h3>You give us</h3>
      <ul>
        <li>Your email address, and your name if you provide one.</li>
        <li>Your Mobile Money number, so a payment prompt can be sent to it.</li>
        <li>Your password, stored only as an Argon2 hash - never in a readable form.</li>
      </ul>

      <h3>Created by using the service</h3>
      <ul>
        <li>
          Your wallet ledger: every deposit, purchase, refund and adjustment, with amounts,
          references and timestamps.
        </li>
        <li>
          Your orders: which service and country, the price, the phone number assigned, and the
          order&apos;s status history.
        </li>
        <li>
          Security records: sign-in attempts, the IP address a request came from, and a salted hash
          of a coarse device fingerprint (browser type plus IP). We store the hash, never the raw
          fingerprint, and use it only to detect one device driving many accounts.
        </li>
      </ul>

      <h3>What we do not collect</h3>
      <ul>
        <li>
          <strong>Your Mobile Money PIN.</strong> It is entered on your own handset and never
          passes through VerifyGH.
        </li>
        <li>
          <strong>Card details.</strong> We do not accept cards, so we never ask for them.
        </li>
        <li>
          <strong>Location, contacts, or advertising identifiers.</strong> We do not use tracking
          or advertising cookies.
        </li>
      </ul>

      <h2>2. Why we use it</h2>
      <ul>
        <li>
          <strong>To provide the service:</strong> take payment, place your order with our
          provider, and show you your number and status.
        </li>
        <li>
          <strong>To keep money correct:</strong> maintain an auditable ledger, reconcile payments,
          and resolve disputes.
        </li>
        <li>
          <strong>To prevent abuse:</strong> detect fraud, account takeover and breaches of our{" "}
          <Link href="/acceptable-use">Acceptable Use Policy</Link>.
        </li>
        <li>
          <strong>To meet legal obligations:</strong> keep financial records, and respond to lawful
          requests.
        </li>
        <li>
          <strong>To contact you:</strong> transactional email about payments, orders and security.
          We do not send marketing email unless you ask us to.
        </li>
      </ul>

      <h2>3. Verification codes and messages</h2>
      <p>
        Where our provider agreement permits it, a verification message is shown to you on your
        order screen. Codes and message bodies are excluded from our application logs, are never
        included in notification emails, and are not shown in staff list views. Support staff can
        see that a message arrived, not what it said, unless a specific dispute requires it.
      </p>

      <h2>4. Who we share it with</h2>
      <p>We share the minimum necessary, and only with:</p>
      <ul>
        <li>
          <strong>Our payment provider,</strong> to collect your Mobile Money payment. They receive
          your phone number, the amount and a reference.
        </li>
        <li>
          <strong>Our verification provider,</strong> to place your order. They receive the service
          and country requested - not your identity.
        </li>
        <li>
          <strong>Our infrastructure providers,</strong> who host the application and database
          under contract.
        </li>
        <li>
          <strong>Authorities,</strong> where we are legally required to, or where there is a
          serious risk of harm.
        </li>
      </ul>
      <p>We do not sell your data, and we do not share it for advertising.</p>

      <h2>5. How long we keep it</h2>
      <ul>
        <li>
          <strong>Financial records</strong> (ledger entries, payments, orders): retained for the
          period Ghanaian financial record-keeping law requires. These are immutable by design and
          are not deleted on request.
        </li>
        <li>
          <strong>Verification codes and SMS text</strong> delivered to a rented number: erased
          30 days after the order finishes. The order itself stays as a financial record.
        </li>
        <li>
          <strong>Security records:</strong> typically 12 months.
        </li>
        <li>
          <strong>Account details:</strong> until you close your account, after which we remove
          what we are not required to keep.
        </li>
      </ul>

      <h2>6. How we protect it</h2>
      <ul>
        <li>Everything is served over HTTPS.</li>
        <li>Passwords are hashed with Argon2; reset tokens are stored only as hashes.</li>
        <li>
          Session tokens live in httpOnly cookies that JavaScript cannot read, with a separate
          anti-forgery token required on every write.
        </li>
        <li>
          Staff access is role-based and least-privilege. Sensitive actions require a written
          reason and are permanently logged.
        </li>
        <li>Credentials and API keys live only in server environment variables.</li>
      </ul>

      <h2>7. Your rights</h2>
      <p>
        Under Ghana&apos;s Data Protection Act, 2012 (Act 843) you can ask us to access, correct or
        delete your personal data, and to explain how we use it. Email{" "}
        <a href="mailto:support@getverifygh.com?subject=Privacy%20request">support@getverifygh.com</a> with
        &quot;Privacy request&quot; in the subject and we will respond within the statutory period.
      </p>
      <p>
        Some data cannot be deleted on request - financial records we are legally required to keep,
        and records needed to investigate an open abuse case.
      </p>

      <h2>8. Cookies</h2>
      <p>
        We use cookies only to keep you signed in and to protect against cross-site request forgery.
        There are no analytics, advertising or tracking cookies.
      </p>

      <h2>9. Changes</h2>
      <p>
        If we make a material change we will tell you before it takes effect.
      </p>

      <h2>10. Contact</h2>
      <p>
        <a href="mailto:support@getverifygh.com">support@getverifygh.com</a>
      </p>
    </>
  );
}
