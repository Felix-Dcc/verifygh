import type { Metadata } from "next";
import Link from "next/link";

import { LegalHeader } from "../_components";

export const metadata: Metadata = {
  title: "Acceptable Use Policy",
  description:
    "What VerifyGH may and may not be used for. Accepting this policy is a condition of purchasing.",
};

export default function AcceptableUsePage() {
  return (
    <>
      <LegalHeader
        title="Acceptable Use Policy"
        updated="30 September 2026"
        summary="VerifyGH is a payment and access layer for legitimate verification needs. It is not a tool for fraud, impersonation, spam, evading bans, or getting around identity checks. Using it for any of those will get your account suspended and your access removed."
      />

      <h2>1. What this policy covers</h2>
      <p>
        This policy applies to everyone who uses VerifyGH. Accepting it is a condition of creating
        an account and of every purchase you make. It sits alongside our{" "}
        <Link href="/terms">Terms of Service</Link>, and where the two overlap, the stricter rule
        applies.
      </p>

      <h2>2. What VerifyGH is for</h2>
      <p>
        VerifyGH lets people in Ghana pay with Mobile Money for verification services supplied by
        an authorised third-party provider. Legitimate uses include:
      </p>
      <ul>
        <li>Receiving a one-time verification code for an account you are entitled to hold.</li>
        <li>
          Testing your own application&apos;s SMS or voice verification flow during development.
        </li>
        <li>
          Keeping a personal number private when signing up to a service that requires phone
          verification, where that service permits it.
        </li>
        <li>Business use where phone verification is a step in a process you are authorised to carry out.</li>
      </ul>

      <h2>3. Prohibited uses</h2>
      <p>
        You must not use VerifyGH, or anything obtained through it, for any of the following. This
        list is illustrative, not exhaustive.
      </p>

      <h3>3.1 Fraud and deception</h3>
      <ul>
        <li>Fraud of any kind, including financial fraud, payment fraud and chargeback abuse.</li>
        <li>
          Impersonating another person, business or public body, or creating accounts in someone
          else&apos;s name.
        </li>
        <li>Creating or supporting fake identities, fake reviews, or fake engagement.</li>
        <li>Phishing, social engineering, or any attempt to obtain credentials or money by deception.</li>
        <li>Money laundering, terrorist financing, or handling the proceeds of crime.</li>
      </ul>

      <h3>3.2 Evading controls</h3>
      <ul>
        <li>
          Evading a ban, suspension, block or other enforcement action taken against you by any
          service.
        </li>
        <li>
          Circumventing identity verification, KYC or AML requirements imposed by any platform,
          financial institution or regulator.
        </li>
        <li>
          Bypassing or defeating a platform&apos;s security controls, rate limits, anti-abuse
          systems, or fraud detection.
        </li>
        <li>
          Creating accounts at scale in breach of a service&apos;s terms, including bulk or
          automated registration.
        </li>
      </ul>

      <h3>3.3 Harm to others</h3>
      <ul>
        <li>Spam, unsolicited bulk messaging, or any form of messaging abuse.</li>
        <li>Harassment, stalking, threats, or intimidation.</li>
        <li>Anything involving the exploitation or endangerment of children.</li>
        <li>Distributing malware, or supporting an attack on any system or network.</li>
      </ul>

      <h3>3.4 Breaching third-party terms</h3>
      <ul>
        <li>
          Using a number in a way that breaches the terms of service of the platform you are
          verifying with. You are responsible for reading and following those terms - we are not
          affiliated with, and do not speak for, any of them.
        </li>
        <li>Reselling, sharing or transferring access to a number you obtained through VerifyGH.</li>
      </ul>

      <h3>3.5 Misuse of VerifyGH itself</h3>
      <ul>
        <li>Sharing your account credentials, or letting another person use your account.</li>
        <li>Creating multiple accounts to get around a limit, a suspension or a pricing rule.</li>
        <li>
          Attempting to interfere with, probe or overload our systems, or to access data that is
          not yours.
        </li>
        <li>Automating VerifyGH outside of an API arrangement we have agreed with you in writing.</li>
      </ul>

      <h2>4. How we enforce this</h2>
      <p>We use proportionate controls to keep the platform safe and lawful:</p>
      <ul>
        <li>
          <strong>Limits.</strong> Deposits, daily spending and order velocity are capped. These
          protect both you and the platform.
        </li>
        <li>
          <strong>Monitoring.</strong> We record authentication activity, coarse device signals and
          order patterns to detect abuse. We record only what this purpose requires - see our{" "}
          <Link href="/privacy">Privacy Policy</Link>.
        </li>
        <li>
          <strong>Review.</strong> Automated signals are advisory. A person reviews them before any
          account is suspended, and that decision is logged with a reason.
        </li>
        <li>
          <strong>Provider rules.</strong> Our upstream provider imposes its own restrictions. Where
          they are stricter than ours, theirs apply, and we will not help you work around them.
        </li>
      </ul>

      <h2>5. What happens if you breach this policy</h2>
      <p>Depending on what happened and how serious it is, we may:</p>
      <ol>
        <li>Contact you to ask about the activity.</li>
        <li>Apply a temporary limit to your account.</li>
        <li>Suspend your account, with the reason recorded and available to you on request.</li>
        <li>Close your account permanently and refuse future service.</li>
        <li>
          Report the matter to the relevant authorities, our payment provider, or the affected
          platform, where we are legally required to or where there is a serious risk of harm.
        </li>
      </ol>
      <p>
        Where we suspend an account, any remaining wallet balance that is not subject to an
        investigation or a legal hold will be returned through the payment channel it came from.
      </p>

      <h2>6. Reporting abuse</h2>
      <p>
        If you believe VerifyGH is being used against this policy, email{" "}
        <a href="mailto:support@getverifygh.com?subject=Abuse%20report">support@getverifygh.com</a> with &quot;Abuse
        report&quot; in the subject and as much detail as you can. We investigate every report.
      </p>

      <h2>7. Changes</h2>
      <p>
        We may update this policy as the service and the law change. If we make a material change
        we will ask you to accept the new version before your next purchase, and the version you
        accepted is recorded on your account.
      </p>
    </>
  );
}
