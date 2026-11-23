import { ArrowRight } from "lucide-react";
import { Link } from "react-router";

import { useAuth } from "@/auth/AuthProvider";
import { SeverityTag } from "@/components/common";

const ENTRIES = [
  {
    to: "/talk",
    title: "Talk it through",
    body: "Explain your situation over a conversation. Every answer quotes the sections of law it rests on, and it asks when a detail would change things.",
  },
  {
    to: "/scenario",
    title: "Something happened to me",
    body: "Describe the incident. See which offences the facts actually establish under the BNS, what procedure follows, and what to do now.",
  },
  {
    to: "/contracts",
    title: "I'm about to sign this",
    body: "Upload a contract. Each risky term is quoted from your document, tied to the section that governs it, with what to ask for instead.",
  },
];

const POOLS = [
  {
    name: "For incidents",
    acts: [
      "Bharatiya Nyaya Sanhita, 2023",
      "Bharatiya Nagarik Suraksha Sanhita, 2023",
      "Bharatiya Sakshya Adhiniyam, 2023",
      "Constitution of India",
      "Information Technology Act, 2000",
      "Sexual Harassment of Women at Workplace Act, 2013",
    ],
  },
  {
    name: "For contracts",
    acts: [
      "Indian Contract Act, 1872",
      "Transfer of Property Act, 1882",
      "Specific Relief Act, 1963",
      "Arbitration and Conciliation Act, 1996",
      "Consumer Protection Act, 2019",
      "Digital Personal Data Protection Act, 2023",
    ],
  },
];

const PRINCIPLES = [
  {
    term: "Quoted, not paraphrased",
    detail:
      "Every finding points at the exact words in your document. A quote that can't be found in the file is thrown away, never shown.",
  },
  {
    term: "Cited to the section",
    detail: "Each concern names the provision that governs it, from the statute text itself, so you can check it.",
  },
  {
    term: "Honest about doubt",
    detail:
      "When facts are missing or a stage of the analysis couldn't run, it says so and lowers its confidence instead of guessing.",
  },
];

/** A real piece of the product: one clause, annotated the way a review shows it. */
function AnnotatedExample() {
  return (
    <figure aria-label="Example of an annotated clause" className="relative rounded-md bg-sheet p-6 sm:p-8">
      <p className="text-xs text-graphite">Employment agreement, clause 9</p>
      <p className="mt-3 font-serif text-lg text-ink">
        The Employee{" "}
        <mark className="bg-marker px-0.5 text-ink">
          shall not, for a period of twenty four months after the termination of employment, directly or
          indirectly engage in any competing business
        </mark>{" "}
        within the territory of India.
      </p>
      <figcaption className="mt-6 border-t border-rule pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityTag severity="CRITICAL" />
          <span className="font-medium">Non-compete after you leave</span>
        </div>
        <p className="mt-2 text-graphite">
          Under section 27 of the Indian Contract Act, an agreement that restrains anyone from a lawful profession
          is void. There is no reasonableness test in India, unlike in the US or UK.
        </p>
        <p className="mt-3 text-xs text-graphite">
          Ask for: delete the clause, or limit it to soliciting the company's current clients.
        </p>
      </figcaption>
    </figure>
  );
}

export function Home() {
  const { user } = useAuth();

  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6">
      <section className="grid gap-12 py-14 sm:py-20 lg:grid-cols-[1.05fr_1fr] lg:items-center lg:gap-16">
        <div>
          <h1 className="max-w-[20ch] text-3xl font-semibold tracking-tight sm:text-4xl">
            What does the law actually say about this?
          </h1>
          <p className="mt-5 max-w-[46ch] text-xl text-graphite">
            Plain answers from Indian statute, with the exact words they rest on.
          </p>

          <ul className="mt-10 border-t border-rule">
            {ENTRIES.map((entry) => (
              <li key={entry.to} className="border-b border-rule">
                <Link
                  to={entry.to}
                  className="group flex items-start gap-4 py-5 transition-colors hover:text-seal-strong"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-xl font-medium">{entry.title}</p>
                    <p className="mt-1 max-w-[52ch] text-graphite">{entry.body}</p>
                  </div>
                  <ArrowRight
                    aria-hidden
                    className="mt-1.5 size-5 shrink-0 text-graphite transition-transform duration-150 group-hover:translate-x-1 group-hover:text-seal"
                  />
                </Link>
              </li>
            ))}
          </ul>
          {!user && (
            <p className="mt-5 text-xs text-graphite">
              You'll sign in first. Your contracts stay private to your account.
            </p>
          )}
        </div>

        <AnnotatedExample />
      </section>

      <section aria-labelledby="principles" className="border-t border-rule py-14">
        <h2 id="principles" className="text-2xl font-semibold tracking-tight">
          How it earns your trust
        </h2>
        <dl className="mt-8 divide-y divide-rule border-y border-rule">
          {PRINCIPLES.map((item) => (
            <div key={item.term} className="grid gap-1 py-5 sm:grid-cols-[16rem_1fr] sm:gap-8">
              <dt className="font-medium">{item.term}</dt>
              <dd className="max-w-measure text-graphite">{item.detail}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="sources" className="border-t border-rule py-14">
        <h2 id="sources" className="text-2xl font-semibold tracking-tight">
          What it reads
        </h2>
        <p className="mt-2 max-w-measure text-graphite">
          2,300 sections across twelve statutes. Repealed and omitted provisions are left out, so nothing dead is
          cited as live law.
        </p>
        <div className="mt-8 grid gap-10 sm:grid-cols-2">
          {POOLS.map((pool) => (
            <div key={pool.name}>
              <h3 className="font-medium">{pool.name}</h3>
              <ul className="mt-3 space-y-1.5 font-serif text-graphite">
                {pool.acts.map((act) => (
                  <li key={act}>{act}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
