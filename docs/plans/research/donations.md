# Sylva: mapping organisms/ecosystems to reserves and conservation donation targets

Date: 2026-10-11. Method: WebSearch/WebFetch only, no accounts, no emails sent. Several official pages returned 403 (IUCN terms, GBIF terms, IUCN API docs), so those items rely on secondary sources and are flagged.

## 1. Datasets (species/ecosystem -> protected area -> managing org)

| Source | Licence / terms found | Verdict for Sylva |
|---|---|---|
| WDPA / Protected Planet | https://www.protectedplanet.net/en/legal : data "may not be put to Commercial Use without the prior written permission of UNEP-WCMC"; commercial use includes "use by any individual or non-profit entity for the purposes of revenue generation"; "You may not redistribute the WDPCA and GD-PAME Data ... in whole or in part by any means"; no sub-licensing "including within Derivative Works"; may publish "providing ... the Data are not downloadable" and attribution is visible. UNEP-WCMC decides what counts as commercial. | Do NOT bundle WDPA rows in the open dataset. Risky if Sylva takes donations/referral fees (revenue generation). Commercial route is IBAT (paid). Link out to Protected Planet pages only. |
| IUCN Red List API / site terms | Official terms page returned 403. Secondary sources (Jentic summary, ZSL national red list terms): token required, free for non-commercial research/education/conservation, commercial use and bulk redistribution need written permission; redistribution via web services prohibited without waiver. Sister IUCN products (Red List of Ecosystems, World Heritage Outlook) have explicit "No Commercial Use" clauses with the same "non-profit revenue generation" definition. Official URL: https://www.iucnredlist.org/terms/terms-of-use | Do not copy category/range data into the open dataset. Store only taxon name/ID and deep-link to the IUCN page. UNVERIFIED: read official terms before any API use. |
| Natura 2000 (EEA) | EEA legal notice https://www.eea.europa.eu/en/about/legal-notice : "EEA materials are published under the CC-BY license"; reuse "without prior permission, free of charge" for commercial or non-commercial purposes, credit EEA. Third-party content excluded; UK boundary data needs a JNCC licence. Downloads: CSV/Excel tables (sites, species, habitats per site) and 100k boundary vectors, yearly edition (https://sdi.eea.europa.eu/catalogue). I did not read the licence on the specific Natura 2000 record. | BEST open source. Standard data forms list species and habitat types per site, giving species -> sites directly for ES and PT. Verify record-level licence (likely CC-BY 4.0). |
| Spain MITECO Banco de Datos de la Naturaleza | Downloads in SHP/GeoJSON/KMZ/GML for Red Natura 2000 and Biosphere Reserves: https://www.miteco.gob.es/en/biodiversidad/servicios/banco-datos-naturaleza/informacion-disponible/rednatura_2000_desc.html . Licence not stated in what I saw (unconfirmed whether CC-BY). | Good for ES; confirm licence on metadata. |
| Portugal ICNF / RNAP | ArcGIS REST at https://sigservices.icnf.pt/server/rest/services/ (POAP layer). A third-party catalogue says CC-BY 4.0; a 2016 OSM list quoted ICNF copyright text restricting use to non-profit/non-offensive. Conflict unresolved. | Unclear. Use Natura 2000 (EEA) for PT sites, or ask ICNF in writing. |
| Key Biodiversity Areas (BirdLife) | https://www.keybiodiversityareas.org/terms-service (v2.0, Nov 2023): commercial use needs prior written permission; "commercial" includes non-profit revenue generation; non-commercial data by request form only, "cannot be ... passed on to third parties, or republished". | Not usable as open data. Link to KBA site only. |
| GBIF | Official terms returned 403. From background knowledge (unverified here): records are CC0, CC-BY or CC-BY-NC per dataset; downloads get a DOI to cite (format doi.org/10.15468/dl.xxxxx, confirmed); search API is free. Filter to CC0/CC-BY to keep NC records out. | Fine for "where does this species occur"; store derived results (e.g. list of Natura site codes), not raw records. |
| Wikidata | CC0. Confirmed only: P814 = IUCN protected area category; per a mapping discussion P137 "operator" is used for site managers. Other property ids (P627 IUCN taxon ID, P846 GBIF taxon ID, P856 website) are from memory and need checking. No property linking species to conservation orgs found. | Use as CC0 glue: taxon -> GBIF/IUCN IDs; protected area item -> operator -> website. Operator coverage for ES/PT parks is probably patchy (unverified). |

Key consequence: protected-area boundary data is the licence-hazardous layer (WDPA, KBA, IUCN). Natura 2000 via EEA is the clean, CC-BY layer for ES/PT.

## 2. Charity directories and donation links

- Every.org (https://docs.every.org/docs/donate-link , https://every.org/charity-api): Nonprofit Search API (key from developer dashboard, account needed), "free for non-commercial use cases", for-profit plans on contact. Donate link is a plain URL `https://www.every.org/<slug-or-EIN>#donate` with params amount, suggestedAmounts, min_value, frequency (ONCE/MONTHLY/YEARLY), designation (not a legal restriction), description, success_url, exit_url, partner_donation_id, partner_metadata, webhook_token, method. Staging at staging.every.org. Never set the email, first_name, last_name params. Coverage is US 501(c)(3); Spanish/Portuguese charities mostly absent, though international ones with a US arm may be listed. Embedding links is by design.
- GlobalGiving API (https://www.globalgiving.org/api/overview/ ; ToS https://training.globalgiving.org/api/legal/terms-of-service/): account + key; no licence fee for non-commercial, commercial may need paid licence; 5-12% nonprofit support fee plus 3% processing which developers must disclose; no recurring via API. GlobalGiving Atlas (https://www.globalgiving.org/atlas/country/spain/) lists about 6,626 Spanish nonprofits with JSON/CSV/API; directory only; licence not checked.
- Charity Navigator GraphQL API (https://www.charitynavigator.org/about-us/financials-and-policies/api-terms-of-use): free display "for their own personal non-commercial use"; caching only for speed. US only, low value for ES/PT.
- Candid Essentials API: paid commercial product; no reliable public pricing found; US-centric. Skip.
- Giving What We Can: no public API found; not a conservation directory.
- Rainforest Trust, World Land Trust: no API/affiliate info found (searches returned nothing). Tropical focus; relevant for global organisms. Gap.
- Rewilding Europe (https://rewildingeurope.com/get-involved/donate/): donate via general gift, special fund, or specific species; European Wildlife Comeback Fund. Closest existing species-linked giving pattern. No API or affiliate programme found.
- SEO/BirdLife, WWF Espana, ANP|WWF Portugal, Quercus, LPN, Fundacion Biodiversidad, Rewilding Spain/Portugal: no machine-readable data or affiliate programme found; searches returned nothing. Plan on hand-curated plain hyperlinks to each org's own donate page (a hyperlink needs no licence).
- Spanish/Portuguese donation rails: nothing verified beyond the GlobalGiving Atlas listing. Gap.

## 3. "Biomimicry gives back" schemes and legal context

- No operating biomimicry royalty/reciprocity scheme found. Biomimicry Institute + NYU MOTH planned COP16 advocacy for protections so gains from bio-inspired design support the ecosystems that inspired them (https://mothrights.org/?p=1262); an opinion piece proposes a biomimicry eco-label returning revenue to the inspiring species (https://www.openglobalrights.org/using-eco-labels-to-encourage-reciprocity-with-nature/). Both are proposals. Sylva's "firm pays the reserve" idea is novel, voluntary and unregulated.
- Critique worth one framing line: https://wiki.p2pfoundation.net/Biomimicry_as_a_New_Enclosure_of_Nature
- Not checked: 1% for the Planet terms, Nature Positive, Earth Species, "Nature as shareholder".
- ABS / Nagoya: Spain Real Decreto 124/2017 (access to genetic resources of wild taxa and control of utilisation; implements EU Reg. 511/2014 and Reg. 2015/1866), https://www.miteco.gob.es/en/biodiversidad/temas/recursos-geneticos/protocolo-de-nagoya/rd-acceso.html . Portugal Decreto-Lei n.o 122/2017 (in force 22 Sep 2017; later amendments not checked). Both concern utilisation of GENETIC RESOURCES (R&D on genetic/biochemical composition) with EU due-diligence duties for users. Biomimicry of form/function (beak shape, termite ventilation) generally does not use genetic material and is outside Nagoya scope (the press release above says current frameworks are limited to genetic resources). Exceptions: work that sequences or screens organisms or uses their biochemistry (silk proteins, enzymes). The Cali Fund (digital sequence information, COP16) is separate (Axios, 2024-11-04). Not legal advice; needs legal review. Sylva giving links are voluntary donations, not ABS benefit sharing, and must not be labelled as such.

## 4. Choosing "the right group" per record

A. Curated mapping (manual). Table: organism_or_ecosystem -> {org, donate URL, rationale, scope ES/PT/global, last_checked}. Ecosystem rows (dehesa, seagrass, etc.) map to a short curated list per ecosystem type. Legally trivial; scales linearly with records (about 109 library records already cluster by organism).
B. Semi-automatic: taxon -> GBIF ID (Wikidata CC0) -> ES/PT occurrences (CC0/CC-BY only) -> intersect with Natura 2000 sites (CC-BY) -> site manager -> manual org match. Produce a candidate list for human review, never auto-publish. Species without ES/PT range fall back to C.
C. Taxon-group fallback: birds -> BirdLife partner (SEO/BirdLife in ES; PT partner not verified), marine -> marine NGOs, tropical forest -> Rainforest Trust / World Land Trust, wetlands -> wetland orgs. Coarse but always works.
D. How others do it: only Rewilding Europe's species-specific giving was confirmed; I did not find a platform that auto-maps species to reserves.

## 5. Ranked recommendation (simplest legal approach first)

1. Hand-curated table + plain outbound links to each org's own donate page. No licence, no API, no money handling. Disclose that Sylva takes no fee. Start with ES/PT orgs plus Rewilding Europe.
2. Add Every.org donate links for orgs listed there (free for non-commercial, URL-only, optional webhook). Only while Sylva is non-commercial; never pass donor PII params. `designation` can carry the species.
3. Use Natura 2000 (EEA CC-BY) + GBIF (CC0/CC-BY) + Wikidata IDs to suggest candidate protected areas per record, human-confirmed, store derived site code/name with attribution. Skip WDPA, KBA, IUCN data; link out instead.
4. Later: corporate "pay the reserve" pledge as a direct contract firm -> NGO, with Sylva as directory not intermediary, to avoid money-transmission, fundraising-licence and ABS-claim risk. Get ES/PT legal review before any referral fee or Sylva holding funds. Intermediaries (GlobalGiving 5-12% + 3%, Every.org) handle payments but add fees/terms.
5. Do not market it as Nagoya benefit sharing.

## Confidence and gaps

- High (read directly or quoted): WDPA terms, EEA CC-BY legal notice, Every.org donate-link params, KBA commercial restriction, GlobalGiving fees.
- Medium: Natura 2000 record-level licence, MITECO licence, Nagoya scope for biomimicry.
- Low/unverified: IUCN official terms (403), GBIF licence text (403), Wikidata property ids beyond P814/P137, ICNF licence conflict, any ES/PT NGO data availability, 1% for the Planet, Rainforest Trust/WLT programmes, Spanish donation rails.
- Next steps: read IUCN and GBIF terms in a browser; open the Natura 2000 EEA record licence; search Every.org for ES/PT orgs; ask ICNF about licence.
