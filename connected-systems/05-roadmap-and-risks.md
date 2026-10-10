# 5. Roadmap and risks: what to do first, and why this might fail

This chapter sequences the work so that each step uses something that already exists, and it lists the ways the whole idea could go wrong. The order follows one rule learned from both repos: give the supply side something useful before asking it to integrate [Certain, from ReachOut's cold-start strategy].

Tags as in the other chapters.

Note added 2026-10-09: the plan (chapter 0) runs Sylva, the nature-in-industry firm and the city supplier in parallel, with the firm as the main focus, and leaves the social algorithm for much later. Read the steps below as the order of work within a shared pilot region, not as gates between the parts. The firm's own three-year shape and stop conditions are in chapter 6.6 and 6.8.

## 5.1 Sequence

### Step 0. Write the shared rule down once (one week)

Create a single `PRINCIPLES.md` that both repos and the blueprint link to. It has four lines, all of which exist somewhere already [Certain]:

1. Work that must be exact is deterministic code. Models only touch language.
2. Every record crossing a boundary is validated against a schema with no extra properties.
3. Every record carries provenance (`ai_extracted`, `expert_validated`, `disputed`), a confidence level and a caveat. A record without them cannot be served.
4. The output of every product is an action off screen. Time in the app is a cost.

The first three are ReachOut's constraints and schema rules. The fourth is new, and it is the thesis made operational.

### Step 1. Backport the provenance flag into Sylva (two to three weeks)

Add `provenance`, `confidence` and `caveat` to every entry in `species_db.json`, defaulting every current entry to `ai_extracted` and `medium` since all 611 came from one model pass [Certain]. Publish the coverage table (84 percent of species missing a pH range) on the product page. Use rainfall ranges in the scorer, since they are far better covered than pH and are currently unused [Certain]. This is small work, it makes Sylva more honest, and it is the dry run for the biomimicry schema.

### Step 2. Pick the region where all three loops overlap (one month of conversations, no code)

The brief already says Spain. The dehesa and montado landscapes of south-west Iberia cover roughly 3.5 million hectares of holm oak and cork oak with extensive grazing; the dehesa is a listed habitat under the EU Habitats Directive (type 6310) and the Sierra Morena dehesas are a UNESCO biosphere reserve [AGFORWARD; UNESCO MAB, both Likely]. Holm-oak decline ("la seca"), driven by the soil pathogen Phytophthora cinnamomi together with drought, is the live threat [Likely]. That makes the dehesa a natural Sylva pilot (an agroforestry system with a real problem), a natural biomimicry partner (protected areas with species lists and staff), and a ReachOut territory (villages with shops). The choice should be made by who will sign, not by the map: one reserve or natural park administration, one agronomist, one municipality.

### Step 3. The biomimicry pilot as a consulting project, not a database (three months)

Do not build the database first. Sign one reserve agreement (consent, scope limited to physical traits and published literature, a fixed fee share). Take one paid or pro-bono industrial question. Run Sylva's ingestion script with the new schema on the open-access literature for the species on the reserve's list. Have the reserve's biologist validate the top twenty records. Deliver one report. Measure three things: hours of validation per record, how many records had a usable supporting sentence, and whether the buyer would pay again. The database is a by-product of the second and third projects.

### Step 4. The place feed as a read-only page (one month)

Before any social features, publish one static page per pilot barrio or reserve buffer: what was planted, what was observed, what was repaired, which shops are stocked, which skills were offered this week. No accounts, no likes, no personalisation. If people visit a page that is identical for everyone in the place and come back, the core bet of chapter 4 has survived its cheapest test. If they do not, nothing expensive was built.

### Step 5. The field layer, the gifted skills inventory and the monthly event (three to six months)

Add the form: record something you did outside, with a photo and a location, flagged `ai_extracted` until a ranger or agronomist validates it. Add the skills inventory to ReachOut's pipeline as a second source next to shops, gifted, with nothing counted. Run one repair-and-teach afternoon a month per pilot place from a kit. The form and the second inventory are small additions to code that exists [Certain]; the event needs a room and two volunteers. Measure monthly verified actions per person and time-to-close-the-app after an action.

### Step 6. Bridging and the published ranking table (after a year of data)

Only now add ranking. Publish the three signals (action conversion, bridging, contribution) as a table anyone can read. Run the barrio-versus-control comparison described in chapter 4.7.

## 5.2 What exists for each step

| Step | Already in a repo | New |
|---|---|---|
| 0 | ReachOut `constraints.md`, schema discipline | One file |
| 1 | Sylva `species_db.json`, ingestion script, scorer | Three fields, one table on the site |
| 2 | Sylva's Spain targeting, Mediterranean knowledge chunks | Agreements |
| 3 | Sylva ingestion and RAG pattern; ReachOut schema gate | New schema, new prompt, one reserve contract |
| 4 | ReachOut barrio assignment and region-scoped streams; Sylva coordinate-based plans | One static page per place |
| 5 | ReachOut five-stage pipeline; Sylva sensor ingest endpoint | A form, a gifted skills inventory, a monthly event kit |
| 6 | Nothing | Ranking, measurement, a control group |

## 5.3 Why this might fail

Each risk below comes with the mitigation that follows from the evidence or the repos. Where a risk is based on history, the source is in `SOURCES.md`.

1. **It becomes another feed.** The moment the place feed gets a scroll and a notification, it competes for attention on attention's terms, and it will lose to products built for that. Mitigation: no infinite scroll, no push notifications, a weekly cadence, and the fourth principle in step 0 enforced by a test, the way ReachOut enforces "no narrative output" with a schema [Certain]. This risk is the one that kills the whole idea if ignored.

2. **The metric gets gamed.** "Verified action" becomes the new like count, and people record walks they did not take. Mitigation: verification by a human with standing (a ranger, a shopkeeper, an agronomist), as in Sylva's lab pH at install and ReachOut's live inventory row [Certain]. Accept that this limits scale. Scale was never the objective.

3. **Bridging silences minorities.** An item that only one group finds useful never surfaces, even when that group is right. This is a known limitation of bridging systems and is discussed by their own proponents [Ovadya and Thorburn 2023, Likely]. Mitigation: bridging ranks but never removes; everything is visible in chronological order one tap away, which is also what the Digital Services Act requires of large platforms [DSA Art. 38, Likely].

4. **The skills layer stays tiny.** Reciprocal accounting of time has stayed small for forty years: the largest US time-bank network reports about 28,000 members in total, Spain's 200 to 300 bancos del tiempo have a few thousand active participants, and Japan's Fureai Kippu declined once public care insurance arrived [Likely]. The models that scaled removed the ledger (Buy Nothing, about 7.5 million members), packaged a cheap event (Repair Cafés, more than 4,000), or kept money (community supported agriculture) [Likely]. Mitigation: no ledger, no balances; skills are gifted search results and monthly events, riding on ReachOut's shopper traffic and Sylva's farmer traffic. If those have no traffic, the skills layer is not the problem.

5. **Algorithmic choice does not change behaviour.** Platforms that let users pick their own feed exist. The research on Bluesky's custom feeds finds many feeds but limited user uptake, and there is little evidence yet on wellbeing outcomes of algorithm choice [Quelle and Bovet 2025; Bluesky middleware 2026, both Likely]. Mitigation: the place feed is not a choice offered inside an attention product. It is the default of a product that has no other feed.

6. **The "doing" metric privileges the able and the time-rich.** A parent working two jobs cannot plant trees on Saturday. Mitigation: observation, repair and teaching count as much as planting; the ledger values an hour as an hour; and the products must work for someone who opens them twice a month.

7. **Location is the privacy cost.** A feed about where you are needs to know where you are. Mitigation: the place is the unit, so the system stores the barrio or the reserve buffer, not the trail. ReachOut already enforces coordinate bounds in its schemas and stores regions by name [Certain]; carry that over and never store a per-person location history.

8. **The legal regime around nature's knowledge shifts.** The benefit-sharing rules for digital sequence information are new and their scope is still being worked out. Mitigation: physical traits and published literature first, written consent with every reserve, and a lawyer before the first genetic or biochemical record. The legal map in chapter 2.7 has the detail.

9. **The thesis is partly wrong, and the design inherits the error.** If empathy is not declining (the 2025 update suggests it has been rising since 2009 [Konrath 2025, Likely]) and if social media's effect on wellbeing is small (as one side of the adolescent debate argues [Orben 2019, Likely]), then a product sold as the cure for an empathy collapse is selling a cure for a disease that may not exist. Mitigation: do not sell it that way. Sell a plan for your land, a shop that has the thing, a report that funds a reserve. The connection is the by-product, measured honestly, and the thesis is tested rather than assumed.

10. **One person cannot carry three products.** Sylva's README says it plainly: do not pretend a solo project is a global engine [Certain]. Mitigation: steps 0 through 4 above are deliberately small, and steps 2 and 3 are mostly conversations. The first real hire is a person who signs reserve agreements, not an engineer.

## 5.4 What would make me stop

Three results that should end the project rather than pivot it:

- Nobody returns to a static place page after the first visit in two pilot places (step 4 fails).
- Validation costs more than an hour per record after the second consulting project, so the database can never be cheaper than a consultant (step 3 fails).
- Verified actions per person do not rise over six months in a pilot barrio against a control (step 5 fails).

Writing these down now is the only protection against the comfort loop the thesis describes, applied to the project itself.
