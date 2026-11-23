# Demo walkthrough

A five-minute path through WhatLawSays, with nothing to set up on stage and
nothing to wait for. Everything runs on this computer: sign-in uses the Firebase
Auth emulator, so no Firebase project is needed.

## Before you present

```bash
./demo.sh
```

This starts the sign-in emulator, the backend (port 8010) and the app
(http://localhost:5173), then makes sure both demo accounts exist with their
reviews done. The first run takes a few minutes: it downloads models, may load
the statute corpus, and reviews six sample contracts (about a minute). After
that it starts in under a minute. `Ctrl+C` stops everything.

| Account | One-click link | Has |
|---|---|---|
| **Priya Sharma** (priya@example.com) | http://localhost:5173/demo/priya | 4 reviews: loaded job offer (Critical), flat lease (High), a scanned copy of the job offer (Critical, read by OCR), a fair contract (Low) |
| **Arjun Mehta** (arjun@example.com) | http://localhost:5173/demo/arjun | 2 reviews: loan agreement (Critical), freelance contract (Critical) |

The password for both is `whatlawsays-demo`, if you would rather type it.

- **Clean slate:** `./demo.sh --reset` deletes and redoes every demo review, for example after deleting one during a demo.
- **Groq key:** with `GROQ_API_KEY` in `backend/.env`, findings get plain-language explanations and Q&A writes real answers.
  - Without the key, red flags still come from the built-in rules, which catch every flag in these contracts.
  - Scenario analysis is weak without the key, so skip step 7 unless it is set.

A strip at the top of every page says **Demo mode** and lets you switch account in one click.

## The path

**1. The promise.** On the home page: two questions people actually have. "Something happened to me" and "I'm about to sign this". Every answer quotes the source word for word and cites the statute.

**2. Sign in.** Click **Sign in**, then **Sign in as Priya Sharma**.
- Point out "Your contracts and reviews are private to your account".
- Real users sign in with Google or email; the demo skips the password.
- You land on **My reviews**.

**3. A contract that should worry you.** Open **01_employment_loaded.pdf**.
- **Overview:** Critical for the employee. 4 critical, 2 high, and a confidence figure.
- **Red flags:** each one quotes the contract exactly (the serif text is always the source's own words), says why it matters for *her* side, and cites the Indian statute behind it. Examples: the 24-month non-compete (section 27, Contract Act), the ₹3,00,000 bond, and the arbitrator chosen by one side.
- **Document:** the contract set like a page, every flagged passage highlighted, with the note pinned in the margin beside it. Click a note to jump to its passage.
- **What to ask for:** replacement wording to send back, with **Copy wording**.
- **Consistency:** the notice periods disagree. 30 days for the company, 90 for her.

**4. Ask it a question.** Click **Ask the contract** and type *What is my notice period?*.
- It answers from the clauses and cites clause 5.
- Without a Groq key it shows the matching clauses unsummarised, and says so.

**5. Take it away.** Click **Report (PDF)** for a report to share with a lawyer.

**6. Two things that build trust.** Back in **My reviews**:
- **09_scanned_employment.pdf** is the same contract as a skewed scan with no text layer.
  - It was read by OCR, it finds the same six flags, and it says plainly that it was a scan.
  - Each finding shows the crop of the page it came from.
- **04_employment_fair.pdf** is a fair contract: Low, no red flags. It doesn't cry wolf.

**7. Talk it through, the flagship (best with a Groq key).** Click **Talk it through**.
- Pick *Someone posted private photos of me online without my consent*.
- The sections appear first, then the answer streams in. Each number in the answer is a citation: click one and its section, in the statute's own words, comes up in the margin.
- Ask a follow-up, such as *They were photos I had sent privately to my ex. Does that change anything?* It keeps the context and searches again.
- When the answer turns on a missing fact, it asks for it.
- Point out the honesty: ask *My salary hasn't been paid for two months*. The twelve Acts don't cover labour law, and it says so instead of improvising.
- **Turn this into a full analysis** hands the conversation to *Something happened*.
- With a key, `./demo.sh` gives Priya this conversation already saved.
- Without a key it still finds the right sections (BNSS s.173 for a refused FIR, TPA s.108 for a withheld deposit), but it shows them unsummarised and says so.

**7b. Something happened (optional, needs a Groq key).**
- Click **Something happened**, pick one of the sample scenarios, and click **Analyse**.
- The result shows which offences the facts make out, element by element, and the procedure and what to do next.

**8. Privacy, live.** Open any of Priya's reviews, then click **Switch to Arjun Mehta** in the demo strip.
- You stay on the same link, and Arjun gets *We can't find that review*.
- The server refuses it. It doesn't say the review exists, so review links can't be probed.
- Open **My reviews**: only his two contracts.

**9. A live upload (optional).** As either account, click **Review a contract**.
- Upload `backend/samples/07_master_services_long.pdf`, choose **SaaS** and **Client**, and click **Review**.
- It takes about ten seconds without Groq, and longer with it. That's 30 clauses, 8 flags, and all three consistency checks.
- Other files to try are listed in [backend/samples/README.md](backend/samples/README.md).

## If something goes wrong

| Problem | Fix |
|---|---|
| "Port 9099 / 8010 / 5173 is already in use" | Another copy is running, or something else holds the port. Stop it (`lsof -iTCP:<port> -sTCP:LISTEN` shows what holds it). |
| "Couldn't sign in as Priya" | `./demo.sh` isn't running, or was restarted while the page was open. Reload. |
| A review is missing | It was deleted during a demo: `./demo.sh --reset`. |
| The first start is slow | It downloads the embedding and reranker models once. |
| "No Postgres" note at start | Reviews are kept in memory and made again on every start. Everything still works. |

Logs for each service are in the folder `./demo.sh` prints at start.
