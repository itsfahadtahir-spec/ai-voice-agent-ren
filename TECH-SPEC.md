# TECH-SPEC — Ren

A voice-first financial wellness coach for GCC professionals carrying credit card debt.

## 01. Problem

Young professionals in the Gulf carry expensive revolving credit card debt. Gulf cards commonly
charge **2.5–3.5% per month** — roughly 30–40% a year — and the monthly figure is the one people
actually feel. Two things make this worse than a spreadsheet problem:

**The shame is the blocker, not the arithmetic.** People know they are in trouble. What stops them
is not a missing calculation, it is that opening the banking app feels bad enough to avoid. A
budgeting app asks you to face the number alone. That is exactly the moment most people quit.

**The numbers they need are not in their head.** "Should I move my balance to another card?" is
unanswerable without today's actual offer — the repayment tenor, the minimum transfer, the early
settlement fee. Those live on bank websites and change without notice.

### Why the existing tools fail

**Budgeting apps solve the wrong problem.** They assume the barrier is information. It is not.
People in card debt already know roughly what they owe; what they lack is the confidence and the
strategy to act on it. A budgeting app answers "where did my money go" when the actual question is
"am I going to be okay, and what do I do first." So the app becomes another surface asking them to
type their worst numbers into a form, alone, with no one on the other end. Most people download one,
enter two cards, and never open it again.

**Chat is not much better.** Typing is slow, and it is editable — which sounds harmless but changes
what people say. Given a text box, someone drafts, deletes, and softens. They round the number down.
They leave out the loan from their brother. Coaching only works on what the person actually admits,
and text invites them to curate. Voice does not: speech is faster than typing, and it comes out
before the internal editor catches it. People say "honestly it's closer to sixty thousand" out loud
in a way they will not type.

**What they actually want is coaching, not accounting.** Restored confidence. Optimism attached to a
concrete strategy. Someone who reflects a strength back at them and gives them a date they can hold
onto. The techniques that do that — visualization, scaling questions, limiting-belief reframes,
self-compassion interrupts, if-then implementation plans — are *spoken* techniques from coaching
practice. They do not survive being turned into UI. "On a scale of zero to ten, how confident are
you?" is a survey question in a form and a coaching question when asked aloud with a pause after it.

**Voice also removes the research burden.** Mid-conversation, someone says "what about moving it to
ADCB?" In a chat flow, they would open three bank sites, hunt for a rate buried in a marketing page,
and lose the thread of the conversation. Ren fetches it live while it is still talking — the person
keeps talking about their 11pm delivery-app habit and the number arrives inside the same breath of
conversation. That is only possible in a medium where the agent can hold the floor while it works,
and it is the specific reason this product is a call and not a chat window.

For the region specifically: expat job loss can mean leaving the country on short notice, which
changes the advice (build the buffer *before* attacking debt). Many users hold Sharia-compliant
cards, where the word is "profit rate", not "interest". Kuwaiti, Bahraini and Omani currencies are
worth far more per unit, so a 500-dinar balance is serious — an agent that treats small numbers as
small problems is actively harmful.

## 02. Architecture

```
  Browser / ElevenLabs widget
            |  WebRTC audio
            v
  ElevenLabs Agent "Ren"
    - Scribe realtime ASR
    - gemini-2.5-flash + 15.5k-char system prompt
    - Flash v2 TTS (voice: Sarah)
    - system tools: skip_turn, end_call
            |
            |  webhook tool call (GET + X-API-Key)
            v
  FastAPI tools API  (main.py)
    /balance-transfer-offers?bank=
    /credit-basics?country=
    /session-token
    - 6h disk-backed cache
    - placeholder filtering
    - bank name aliasing
            |
            |  POST /v1/web/extract  (Bearer)
            v
  context.dev Extract  --crawls-->  bank's live balance transfer page
```

**Conversation flow.** ElevenLabs handles audio and turn-taking. When the conversation reaches a
real product question, the LLM calls `get_card_offers` with the bank name as the user said it. The
tool is configured `execution_mode: immediate` with `pre_tool_speech: force`, so Ren speaks
("give me one second, I'm pulling that up") *while* the request is in flight. Measured cold
extracts run 1–10 seconds; a 3-second `soft_timeout` filler covers the gap so the user never hears
dead air.

**Data flow for a lookup.** Bank name → normalized and alias-resolved (`enbd`, `rak`, `Abu Dhabi
Commercial Bank` all resolve) → 6-hour cache checked → on miss, `POST /v1/web/extract` to
context.dev with a five-field JSON Schema, `maxPages: 1, maxDepth: 0` → returned values screened
against a placeholder list → cached → returned with `as_of` and `fetched_at` so the agent can
honestly say "as of today".

**Security.** The ElevenLabs key and context.dev key never leave the server. Tool endpoints require
`X-API-Key` and **fail closed** — with no `TOOLS_API_KEY` set they return 503 rather than serve
traffic, because the deployment URL is public and every Extract call costs 10 credits.
`/session-token` mints a short-lived ElevenLabs conversation token so a browser can start a call
without holding a secret.

## 03. Tool rationale

**ElevenLabs** — chosen for platform features we actually depend on, not just TTS:

- `soft_timeout_config` speaks a contextual filler when the LLM is slow. Without it a 15.5k-char
  prompt produced audible dead air that read as "the app is broken".
- `pre_tool_speech: force` + `execution_mode: immediate` let Ren talk while a webhook runs, which
  is what makes a 3–10 second live fetch tolerable in conversation.
- `skip_turn` lets Ren deliberately stay silent. A coaching agent that fills every pause cannot run
  a visualization exercise.
- Webhook tools with secret headers meant no bespoke auth layer.

**context.dev** — the offers we need sit on bank marketing pages behind JS rendering and anti-bot
protection, and they change without notice. We used three of its endpoints, each for a distinct job:

**1. Extract (`POST /v1/web/extract`) — the runtime lookup.** This is the one in the live call path.
We pass the bank's URL, a five-field JSON Schema, and instructions telling it to keep values short
enough to read aloud. It returns schema-shaped JSON, which matters more than it sounds: the response
is injected into an LLM turn mid-conversation, so a page of raw Markdown would blow the turn budget
and add seconds of latency. `maxPages: 1, maxDepth: 0` restricts it to the single page instead of
crawling the site — the difference between a 4-second answer and a 346-second one (measured on BBK).
`factCheck: true` is on. One endpoint replaced a browser pool, a proxy rotation, and a bespoke
parser per bank.

**2. Web Search (`POST /v1/web/search`) — build-time page discovery.** We did not guess bank URLs.
For each bank we searched for its balance transfer page and inspected the results. This was worth
far more than convenience: the results exposed that searching for GCC banks surfaces QNB
**Pennsylvania**, Commercial Bank of **Sri Lanka**, and National Bank of **Canada**. Trusting search
ranking would have had Ren quoting US rates to a user in Doha. It also revealed which banks publish
a dedicated HTML page at all — which is what set our coverage boundary.

**3. Extract against PDF URLs — evaluated and rejected.** Several UAE and Saudi banks publish balance
transfer terms only as PDFs. Extract parses them successfully (200 in 4–8 seconds), so this looked
like free coverage. It is not: the values come back mis-mapped, because a terms-and-conditions PDF
contains dozens of numbers and nothing labels which one is the balance transfer tenor. Documented in
Feasibility below. We kept the finding and dropped the feature.

**Planned but unused: Monitors.** `create-monitor` with `change.detected` webhooks is the correct way
to keep offers fresh, and it is v2 rather than today's TTL-based cache.

**How we used Devin** — Devin wrote most of this code, but its real contribution was verification,
and that is what changed the shape of the product. The workflow was: propose a bank, fetch its page
live, inspect the actual fields returned, and only then commit the URL. That loop rejected more banks
than it accepted, and it surfaced four things that reading the code would never have shown:

1. **The `"null"` string bug.** Extract returns the literal text `"null"` as a field value rather
   than omitting the field. Our filter was `if data.get(name)` — and `"null"` is truthy in Python, so
   it passed straight through. Ren would have said *"the maximum repayment period is null"* aloud to
   a user. Caught by reading real responses, not by reasoning about the code. Fixed with a
   placeholder screen that also catches `"not mentioned"`, `"n/a"` and friends.
2. **The 346-second extract.** BBK's page took nearly six minutes and returned nulls in all five
   fields. That single measurement justified cutting the request timeout from 120s to 20s and told us
   Bahrain was not viable.
3. **The mis-mapped PDF figures.** Al Rajhi's PDF yielded a repayment period of "164 months" and
   FAB's yielded "55 days". Both are plausible-looking, silently wrong, and would have been spoken
   with a bank's name and "as of today" attached.
4. **A prompt that could not work.** The original system prompt instructed the agent to never defer
   to the bank *and* never invent a number — while having zero tools registered. Inspecting the live
   agent config surfaced the contradiction, which would otherwise have produced confident fabricated
   rates on the first real call.

Devin also configured the ElevenLabs agent through the API rather than the dashboard — voice, TTS
model, `soft_timeout_config`, `max_duration_seconds`, `max_tokens`, the `skip_turn` and `end_call`
system tools, and registering both webhook tools with their auth headers — and rendered TTS samples
of five candidate voices with a GCC-specific line so the voice could be chosen by ear rather than by
label.

## 04. Feasibility — how this was scoped to six hours

What was cut, and why:

- **No frontend.** There is no call UI in this repo. The demo runs on the ElevenLabs widget. A
  custom WebRTC call screen was scoped and deliberately dropped; `/session-token` exists so it can
  be built next without touching the backend.
- **UAE and Qatar only.** Six banks, each verified. Saudi, Kuwait, Bahrain and Oman were tested and
  cut (see below) rather than shipped broken.
- **In-process cache, not Redis.** A 6-hour disk-backed dict. Correct enough at this scale, and
  documented as the first thing to replace.
- **Curated bank URLs, not discovery.** No automatic bank-page finding. A hand-verified map is
  boring and correct; automatic discovery was demonstrably wrong.
- **No cross-session memory.** ElevenLabs memory tools exist and are unused, so Ren cannot recall a
  previous session's commitment.

**What testing forced us to cut.** Saudi, Kuwait, Bahrain and Omani banks publish no scrapable
balance-transfer page. BBK took **346 seconds** and returned `"null"` in all five fields. Extracting
from the PDF terms instead technically worked but mis-mapped fields — Al Rajhi yielded a repayment
period of **164 months** and FAB yielded **55 days** (that is the interest-free grace period). Both
would have been read aloud with a bank's name and "as of today" attached. Those banks now refuse
explicitly: *"I can't get their exact numbers today, and I'd rather not guess."*

This is the central engineering decision in the project. Coverage was traded for truthfulness. For
a debt coach, a confidently wrong figure is worse than an admitted gap.

## 05. Extensibility — v2

**Correctness first**

1. **Hand-curate the PDF banks.** Five fields per bank, read by a human, stamped with `verified_on`.
   The only approach that is actually correct for FAB, Mashreq, DIB, Al Rajhi and SNB.
2. **Verify the debt burden caps.** Only the UAE's 50% is confirmed. The other five countries return
   a `debt_burden_note` instructing Ren to state no percentage. They need checking against each
   regulator, then filling in with a date.
3. **context.dev Monitors** on each bank page, with `change.detected` webhooks invalidating the
   cache. Offers stop going stale between calls instead of relying on a TTL.

**Product**

4. **The call UI.** `@elevenlabs/react` against `/session-token`: call states, timer, mute, orb, no
   transcript. The thing that makes Ren feel like a phone call rather than a chat widget.
5. **Cross-session memory** via ElevenLabs memory tools, so Ren opens with *"last time you committed
   to the 11pm rule — how did that go?"* The prompt already asks it to remember a concrete detail;
   today that instruction cannot survive the end of the call.
6. **Real user auth on `/session-token`.** CORS limits which pages can call it; it does not stop a
   direct request. Anyone can currently open calls against our ElevenLabs minutes.

**Scale**

7. Redis cache shared across instances, replacing the per-instance dict.
8. Per-bank extraction instructions rather than one generic schema, so PDF sections can be targeted.
9. Arabic support. The agent is English-only today (`eleven_flash_v2`), which also means Arabic bank
   names and "dirham"/"riyal" are pronounced by an English model. A pronunciation dictionary is the
   cheap fix; a multilingual agent is the real one.
