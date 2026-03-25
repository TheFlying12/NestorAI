import { Header } from "../landing/Header";
import { Footer } from "../landing/Footer";

export const metadata = {
  title: "SMS Messaging Policy | Nestor AI",
  description: "How Nestor AI collects opt-in consent for SMS notifications and how to manage your preferences.",
};

export default function SmsPolicyPage() {
  return (
    <div
      style={{
        background: "#FAF9F6",
        color: "#2B2B2B",
        fontFamily: "'Manrope', -apple-system, BlinkMacSystemFont, sans-serif",
        lineHeight: 1.6,
        minHeight: "100vh",
      }}
    >
      <Header />

      <main className="max-w-3xl mx-auto px-5 py-16">
        <h1
          className="font-display font-bold mb-2"
          style={{ fontSize: "clamp(1.8rem, 4vw, 2.6rem)", color: "#2B2B2B" }}
        >
          SMS Messaging Policy
        </h1>
        <p className="text-sm mb-10" style={{ color: "#6B7C8F" }}>
          Last updated: March 2026
        </p>

        <Section title="Program Description">
          <p>
            Nestor AI sends SMS notifications to users who have explicitly opted in. Messages include
            budget alerts, habit reminders, job-search follow-ups, and replies to inbound SMS
            messages you send to us. Message frequency varies based on your activity and
            notification preferences.
          </p>
        </Section>

        <Section title="How We Collect Opt-In Consent">
          <p className="mb-4">
            SMS consent is collected exclusively through the Nestor AI account settings page
            (<strong>nestorai.co/account</strong>). To opt in, a user must:
          </p>
          <ol className="list-decimal pl-6 space-y-2">
            <li>Sign in to their Nestor AI account.</li>
            <li>Navigate to <strong>Account → Phone number (SMS)</strong>.</li>
            <li>Enter their US mobile phone number.</li>
            <li>
              Check the following consent checkbox before saving:
              <blockquote
                className="mt-2 p-3 rounded-lg text-sm italic"
                style={{ background: "#F1EFEA", borderLeft: "3px solid #5E6F52", color: "#2B2B2B" }}
              >
                "I agree to receive SMS notifications from Nestor. Msg &amp; data rates may apply.
                Reply STOP to unsubscribe at any time."
              </blockquote>
            </li>
            <li>Click <strong>Save phone</strong>.</li>
          </ol>
          <p className="mt-4">
            The Save button is disabled until both a valid phone number is entered and the consent
            checkbox is checked. Consent is never pre-selected.
          </p>
          <p className="mt-4">
            After saving, the user receives a confirmation SMS:
          </p>
          <blockquote
            className="mt-2 p-3 rounded-lg text-sm italic"
            style={{ background: "#F1EFEA", borderLeft: "3px solid #5E6F52", color: "#2B2B2B" }}
          >
            "Welcome to Nestor! You've opted in to SMS notifications. Reply STOP to unsubscribe,
            HELP for help. Msg &amp; data rates may apply."
          </blockquote>
        </Section>

        <Section title="Opt-Out Instructions">
          <p>
            Reply <strong>STOP</strong> to any Nestor AI SMS message to unsubscribe immediately.
            You will receive a final confirmation text and no further messages will be sent.
          </p>
          <p className="mt-3">
            You may also remove your phone number at any time from{" "}
            <strong>Account settings</strong> in the Nestor AI app.
          </p>
        </Section>

        <Section title="Help">
          <p>
            Reply <strong>HELP</strong> to any message for assistance, or contact us at{" "}
            <a href="mailto:support@nestorai.co" style={{ color: "#5E6F52" }}>
              support@nestorai.co
            </a>
            .
          </p>
        </Section>

        <Section title="Message &amp; Data Rates">
          <p>
            Message and data rates may apply. Message frequency varies. Nestor AI is not
            responsible for any fees charged by your mobile carrier.
          </p>
        </Section>

        <Section title="Supported Carriers">
          <p>
            Our SMS program is available on all major US carriers including AT&amp;T, T-Mobile,
            Verizon, and Sprint. Carrier support is not guaranteed for all carriers.
          </p>
        </Section>

        <Section title="Privacy">
          <p>
            Phone numbers collected for SMS notifications are stored securely and are never sold or
            shared with third parties for marketing purposes. For full details, see our{" "}
            <a href="/about" style={{ color: "#5E6F52" }}>
              Privacy Policy
            </a>
            .
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Nestor AI<br />
            <a href="mailto:support@nestorai.co" style={{ color: "#5E6F52" }}>
              support@nestorai.co
            </a>
          </p>
        </Section>
      </main>

      <Footer />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2
        className="font-display font-bold mb-3"
        style={{ fontSize: "1.15rem", color: "#2B2B2B" }}
      >
        {title}
      </h2>
      <div style={{ color: "#444", fontSize: "0.95rem" }}>{children}</div>
    </section>
  );
}
