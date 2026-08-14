# iKAN WhatsApp Outreach — Fix Brief

Handoff document for the Claude session running the WhatsApp automation.
Derived from a full read of the 250-conversation export (2026-08-14).

---

## 1. Where we actually are

| Metric | Value |
|---|---|
| Conversations opened | 250 |
| Never got past the opener | 196 (78%) |
| Pitch delivered | 63 |
| Stalled after pitch | 39 |
| Hot leads | 2 |
| Closed sales | 0 |

**Unit economics.** Nigeria marketing message = $0.0516 ≈ ₦77. One sale = ₦250,000.
Break-even is **1 sale per ~3,250 conversations**. At 250 conversations we are 7.7%
of the way through a single break-even cycle, so zero sales so far proves nothing
about viability. Volume is the right long-term call — the account is approved for
2,000/day. But every defect below multiplies by that volume, so they get fixed first.

At 2,000/day the spend is ~₦154,000/day (~₦4.6M/month). A 20% unqualified rate is
~₦900k/month spent messaging people who already have websites.

---

## 2. Defects, ranked by damage

### 2.1 The agent kills buying signals — CRITICAL

Hopement Nigeria:

```
Them: How much is it ?
AI:   No problem, thanks for letting me know. Take care.
```

A direct price question answered with a goodbye. A human returned six hours later
with "250K baseline", got "ok", and the thread died.

**But the correct behaviour already exists in the system.** Solar Lux Energy, same day:

```
Them: How much
AI:   We start from ₦250,000.
AI:   That covers a custom customer-focused site, mobile-friendly, basic SEO,
      12 months hosting, and one round of revisions.
```

**Action: make the Solar Lux behaviour the default.** A price question is the
strongest signal available and must never route to a closing pleasantry.

### 2.2 Every close is a conversation terminator — CRITICAL

Observed closes: *"Take care." / "I'll be here." / "Cool, take your time." /
"Anytime!" / "Good luck with the site." / "Thanks for the honesty, all the best."*

The agent is optimising for politeness and ending threads. The 39 leads sitting in
"Pitched" are not cold — they were closed by our own agent.

**Action: no message may end without a question or a concrete next step**
(a named time, a specific offer). "Take care" is a banned ending unless the
prospect has explicitly declined twice.

### 2.3 We pitch to autoresponders — HIGH

35 of ~54 "replies" are the business's own greeting bot:

- *"Welcome to Klaxhair. We're glad to have you here."*
- *"Thank you for contacting Coco De Mer Spa!"*
- *"We are here to attend to u"* (Infinity Autos)
- *"Hi! Welcome to SOLAR LUX ENERGY..."* — fired twice, and a human follow-up
  went straight into the loop.

The real human reply rate is a fraction of the headline 25%. This is the main
reason "replies" don't convert — many were never people.

**Action:** classify the first inbound. If it matches a greeting-bot pattern
(instant reply, generic welcome text, service-menu prompt, emoji-bracketed banner),
do **not** pitch. Wait for a second, human-shaped message, or re-engage later.

### 2.4 The opener manufactures false replies — HIGH

Current: *"Good day, please I am trying to reach the management team at {business}
on this contact line. My name is Sophie from iKAN GROWTH ENTERPRISE."*

This reads as an incoming customer (or a debt collector). It is *why* the reply
rate looks good — responses are *"How may I help you?"*, *"Would you like your
massage at our spa or at your home?"* People answer thinking business is walking in.
The switch to a sales pitch then destroys trust instantly.

High reply rate + zero interest is the exact signature of this bait-and-switch.

**Action:** state purpose in the first message. Solar Lux's variant is close:
*"I wanted to speak with management about a website to help {business} get more
customers — is this the right contact?"* Fewer replies, dramatically better ones.

### 2.5 One identical paragraph, 63 times — MEDIUM

The same pitch went byte-for-byte to a dental clinic, a hair salon, a massage spa,
a car dealer, a guest house and a safety-equipment firm — always name-dropping
*"dental, restaurants, real estate"*. Every non-matching prospect reads that and
sees someone else's business.

**Action:** the category is already in the lead data. Swap the proof example to
match the prospect's niche.

### 2.6 Unsolicited PDF within two minutes — MEDIUM

Every thread dumps the company profile before interest exists. Nobody opens a
stranger's document on WhatsApp, and it burns the credibility asset at the moment
of lowest attention.

**Action:**
- Lead with **one line of proof + a live link** to a real site we built.
- Prefer **screenshots** (render in-chat) over documents (require a decision).
- Send the PDF **on request**, or once the prospect has engaged.

The PDF itself is good and should be kept — it answers the real credibility
objection seen in the data (Sewgull: *"How big are you?"* → *"U beta go and grow
urself first"*). It is a closing asset, not an opener.

---

## 3. The offer change

Two objections dominate the export:

1. **Credibility** — *"How big are you?"*
2. **Commodity/DIY** — Roots N Tips: *"is there anyone that cannot build their own
   websites with all the tools available at little or no cost? I'm tired of people
   trying to sell things we all can do in less than 30 minutes."*

Neither "free consultation" (reads as a pressure trap) nor free work (devalues the
₦250k, attracts non-buyers) solves these.

**Show a finished site in their own category, then offer a custom preview to the
few who engage.**

There are five concept builds, one per niche. Run outreach **one niche at a time**
so every prospect sees a site built for a business like theirs:

| Niche | Build |
|---|---|
| Lounge / bar | sable-house-lagos.vercel.app |
| Dental & healthcare | dental-bay-ten.vercel.app |
| Real estate | real-estate-woad-theta.vercel.app |
| Hotel / shortlet | site-iota-two-75.vercel.app |
| Automotive | arclane-eta.vercel.app |

This costs nothing per lead — one link per campaign, no new builds — and it fixes
defect 2.5 (the niche-mismatched proof) at the same time.

- Against credibility: a finished, working site they can open on their phone.
- Against DIY: it visibly is not a 30-minute template.

**Then gate the custom preview behind real engagement.** For a prospect who replies
as a human and qualifies as the decision-maker, build them a preview of their own
site and send the link. That is a handful per week, not per day — affordable in
build time, and it is the strongest close available:

> *"I went ahead and put together a first version for {business} so you can see it
> rather than take my word for it: {link}. No charge, no obligation."*

Do not attempt a preview per lead. At 2,000 conversations/day that is not buildable,
and it is not needed — the niche build does the persuading up front.

---

## 4. Target conversation flow

1. **Opener** — state purpose plainly, ask if this is the right contact.
2. **Classify the reply** — autoresponder → hold, do not pitch. Human → continue.
3. **Qualify** — right person? If not: *"who on your team handles the website?"*
4. **One-line proof** — niche-matched, with a live link.
5. **Offer the free preview** — *"Let me build you a free preview of your homepage.
   No charge, no obligation."*
6. **Deliver the preview link.**
7. **Price** — direct, with the value breakdown, the moment it is asked.
8. **Always** close on a question or a named next step.

---

## 5. Hard rules for the agent

- Never end a message without a question or a concrete next step.
- Never respond to a price question with a pleasantry. State ₦250,000 and what it covers.
- Never pitch into a detected autoresponder.
- Never send the PDF unrequested before the prospect has engaged.
- Never claim a capability, office, or client we cannot evidence.
- On an explicit no: acknowledge once, leave the door open, stop. Do not argue.
- Match the proof example to the prospect's niche.

---

## 6. Upstream: lead quality

At ₦77/message, unqualified leads are a direct cash cost. Before loading the dialer,
run the list through the qualification stages in this repo:

- **Tier 1 (free)** — drop anything whose Maps listing shows a live website.
  Keep listings whose website is dead or parked; those businesses still need one.
- **Tier 2 (~₦0.50/lead)** — web-search the survivors. Many have a site Maps never
  linked, or run on Instagram only. Anything found → drop.

The export contains exactly the leads this removes: *"We are working on a website
already"* (Naija Elegant Events), *"we have give someone already to get it done"*
(Infinity Autos).

Then rank by `score_tier`. A business with no website and 240 reviews at 4.6 stars
can write a ₦250k cheque; one with 3 reviews cannot. Message `hot` first.
