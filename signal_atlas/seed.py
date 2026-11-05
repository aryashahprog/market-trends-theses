"""First edition (2026-11-05). Every evidence item below was retrieved and read from its public source
while building this edition; statements are paraphrased or short-quoted, never full-text copies."""
from __future__ import annotations

import sqlite3
from typing import Any

from .adapters.base import RawItem
from .db import dumps, loads, tx
from .pipeline import upsert_document, write_snapshot
from .timeutil import iso, parse_iso

EDITION_DATE = "2026-11-05"
PUBLISHED_AT = "2026-11-05T16:00:00Z"
VERIFIED_AT = "2026-11-05T15:45:00Z"  # verification window for first-edition retrievals: 15:30–16:00 UTC

SOURCES: list[tuple[str, str, str, str, str]] = [
    ("milkroad", "Milk Road", "discovery", "https://milkroad.com/",
     "Public sitemap and page metadata only; robots.txt honoured; no article text stored."),
    ("marketwatch", "MarketWatch (public RSS)", "discovery", "https://www.marketwatch.com/",
     "Headlines and RSS summaries only from public Dow Jones feeds; site pages not scraped."),
    ("sec_edgar", "SEC EDGAR", "primary", "https://www.sec.gov/edgar/search/",
     "Official EDGAR search API; declared User-Agent with contact; well under SEC fair-access limits."),
    ("priceofcompute", "Price of Compute", "dataset", "https://www.priceofcompute.com/indices",
     "Free public API (no key, <1,000 req/day); cached; attribution shown with every chart."),
    ("silicondata", "Silicon Data index page", "dataset", "https://www.silicondata.com/products/silicon-index",
     "Public page values observed at retrieval time (robots allows); no paid data accessed."),
    ("ramp_ai_index", "Ramp AI Index", "dataset", "https://ramp.com/data/ai-index",
     "Public research page; headline figures only, linked to source."),
]

# url -> (source_id, title, source_type, published_at, event_date)
DOCS: dict[str, tuple[str, str, str, str | None, str | None]] = {
    "https://milkroad.com/podcast/the-most-important-chart-in-ai-just-exposed-a-massive-contradiction-naWi9gIsWVE/":
        ("milkroad", "The Most Important Chart in AI Just Exposed a Massive Contradiction", "podcast",
         "2026-11-02", "2026-11-02"),
    "https://milkroad.com/podcast/the-ai-compute-shortage-is-about-to-get-much-worse-8e6GwkOEpPk/":
        ("milkroad", "The AI Compute Shortage Is About to Get Much Worse", "podcast", "2026-10-22", None),
    "https://milkroad.com/podcast/ai-stocks-just-hit-a-rare-bottom-signal-is-the-worst-over-Anhl5SoXU3Y/":
        ("milkroad", "AI Stocks Just Hit a Rare Bottom Signal", "podcast", "2026-11-04", None),
    "https://milkroad.com/ideas/wait-cheaper-ai-is-good-for-anthropic/":
        ("milkroad", "Wait, cheaper AI is good for Anthropic?", "newsletter_analysis", "2026-10-28", None),
    "https://milkroad.com/ideas/intel-s-worst-day-since-1974/":
        ("milkroad", "Intel's worst day since 1974", "newsletter_analysis", "2026-11-02", None),
    "https://milkroad.com/ideas/why-our-team-keeps-buying-spacex/":
        ("milkroad", "Why our team keeps buying SpaceX", "newsletter_analysis", "2026-11-04", None),
    "https://milkroad.com/news/glxy-made-323m-now-for-the-hard-part/":
        ("milkroad", "GLXY made $323M. Now for the hard part", "news_brief", "2026-10-28", None),
    "https://www.priceofcompute.com/indices":
        ("priceofcompute", "Price of Compute GPU indices", "pricing_dataset", None, "2026-11-05"),
    "https://priceofcompute.com/api/v1/prices/h100-sxm":
        ("priceofcompute", "Price of Compute — H100 SXM daily price (API)", "pricing_dataset", None, "2026-11-05"),
    "https://www.silicondata.com/products/silicon-index":
        ("silicondata", "Silicon Data Silicon Index", "pricing_dataset", None, "2026-11-05"),
    "https://ramp.com/data/ai-index":
        ("ramp_ai_index", "Ramp AI Index", "adoption_dataset", None, "2026-10-23"),
    "https://www.sec.gov/Archives/edgar/data/2130357/000162828026067168/anthropicpbc-sx1.htm":
        ("sec_edgar", "Anthropic, PBC — S-1 filed 2026-10-26", "regulatory_filing", "2026-10-26", "2026-09-30"),
    "https://www.sec.gov/Archives/edgar/data/1404655/000119312526447363/hubs-20260930.htm":
        ("sec_edgar", "HubSpot, Inc. — 10-Q filed 2026-11-04", "regulatory_filing", "2026-11-04", "2026-09-30"),
    "https://www.sec.gov/Archives/edgar/data/1297989/000129798926000031/exls-20260930.htm":
        ("sec_edgar", "ExlService Holdings — 10-Q filed 2026-10-27", "regulatory_filing", "2026-10-27", "2026-09-30"),
    "https://www.sec.gov/Archives/edgar/data/50863/000005086326000191/intc-20260926.htm":
        ("sec_edgar", "Intel Corp — 10-Q filed 2026-10-30", "regulatory_filing", "2026-10-30", "2026-09-26"),
    "https://www.sec.gov/Archives/edgar/data/1181412/000162828026066880/spcx-20260930.htm":
        ("sec_edgar", "Space Exploration Technologies — 10-Q filed 2026-10-22", "regulatory_filing",
         "2026-10-22", "2026-09-30"),
    "https://www.sec.gov/Archives/edgar/data/717826/000162828026065962/a2026q3forfiling.htm":
        ("sec_edgar", "Ericsson — Q3 2026 report (6-K) filed 2026-10-15", "regulatory_filing",
         "2026-10-15", "2026-09-30"),
}

MR_CHART = "https://milkroad.com/podcast/the-most-important-chart-in-ai-just-exposed-a-massive-contradiction-naWi9gIsWVE/"
POC = "https://www.priceofcompute.com/indices"
POC_H100 = "https://priceofcompute.com/api/v1/prices/h100-sxm"
SD = "https://www.silicondata.com/products/silicon-index"
RAMP = "https://ramp.com/data/ai-index"
S1 = "https://www.sec.gov/Archives/edgar/data/2130357/000162828026067168/anthropicpbc-sx1.htm"
HUBS = "https://www.sec.gov/Archives/edgar/data/1404655/000119312526447363/hubs-20260930.htm"
EXLS = "https://www.sec.gov/Archives/edgar/data/1297989/000129798926000031/exls-20260930.htm"
INTC = "https://www.sec.gov/Archives/edgar/data/50863/000005086326000191/intc-20260926.htm"
SPCX = "https://www.sec.gov/Archives/edgar/data/1181412/000162828026066880/spcx-20260930.htm"
ERIC = "https://www.sec.gov/Archives/edgar/data/717826/000162828026065962/a2026q3forfiling.htm"

# (url, claim_type, stance, statement)
Ev = tuple[str, str, str, str]

SIGNALS: list[dict[str, Any]] = [
    {
        "id": "gpu-rent-vs-token-deflation",
        "title": "GPU rent is rising while the price of a token keeps falling",
        "dek": "Scarcer capacity and cheaper output at the same time — the spread between them is where new "
               "infrastructure businesses get built.",
        "sector": "AI infrastructure",
        "themes": ["Compute economics", "Inference efficiency", "Compute markets"],
        "direction": "Strengthening",
        "what_changed": "Two independent public GPU-rental trackers show on-demand prices up since mid-August 2026, "
                        "led by older parts: Price of Compute's composite index stood at 142.28 on Nov 5 (base 100 on "
                        "Aug 10), with A100 SXM 80GB at 140, H200 SXM at 155 and H100 SXM at 124. Over a similar window, Ramp's "
                        "card-spend panel shows the blended OpenAI/Anthropic price businesses pay per million tokens "
                        "fell 26.8% (week ending Oct 23 vs. Sep 25) while token volume rose 37.1%.",
        "why_now": "Demand has broadened beyond frontier labs: older A100-class capacity is repricing upward, which "
                   "suggests buyers are absorbing whatever is available rather than waiting for newer supply. At the "
                   "same time model vendors are cutting cost per completed task (the Anthropic S-1 cites ~25–40% "
                   "reductions for newer models), so output deflates while the key input inflates.",
        "market_indication": "Margin pressure moves to whoever sits between GPU-hours and tokens. Serving providers "
                             "without efficiency gains or long-dated capacity face a squeeze; operators that extract "
                             "more completed work per GPU-hour (batching, caching, scheduling, routing to cheaper "
                             "models) capture the spread. Competing public price indices indicate compute is becoming a "
                             "priced, benchmarkable commodity.",
        "startup_opportunity": "Inference-efficiency software sold on measured cost per completed task (KV-cache "
                               "reuse, scheduling, model routing); compute procurement and hedging tools built on "
                               "public indices; marketplaces that re-monetize older-generation GPUs.",
        "corporate_buyer": "CIO and finance teams with AI line items facing rising reserved/on-demand capacity costs "
                           "but falling API token prices — they need build-vs-buy-vs-API analysis and ways to lock "
                           "in capacity.",
        "value_chain": ["GPU rental & neoclouds", "Inference serving software", "Model APIs",
                        "Enterprise AI budgets", "Compute indices & derivatives"],
        "confidence": "Medium",
        "corroboration": "Corroborated (direction)",
        "confidence_rationale": "Direction is corroborated by two independent rental trackers and a large card-spend "
                                "dataset. Levels differ materially between trackers (H100 on-demand: $4.07/hr median "
                                "vs $2.97/hr on the same day), the index history is under three months long, and the "
                                "token-price measure covers spend with two vendors only. Single-SKU series can be noisy (A100 PCIe 80GB "
                                "alternates between ~117 and ~212 day to day), so this signal relies on the composite and stable SKUs.",
        "next_validation": "Check whether the composite holds above ~130 across the next scheduled refreshes; compare "
                           "Ramp's next tokenomics release for spend growth vs volume; check whether Silicon Data's "
                           "H100 index moves in the same direction as Price of Compute's.",
        "falsifier": "Rental indices revert toward their August base while token volume growth stalls — implying a "
                     "short-lived capacity squeeze rather than a durable spread.",
        "thesis_sentence": "GPU-hour prices are rising while the price of a token falls, so value is shifting to "
                           "software and operators that turn each GPU-hour into more completed work.",
        "analyst_scores": {"relevance": 5, "impact": 4},
        "match_terms": ["gpu", "gpus", "h100", "a100", "b200", "compute", "rental", "token", "tokens", "inference",
                        "neocloud", "coreweave", "nebius", "nvidia", "data center"],
        "match_min": 2,
        "chart": {"series": ["poc:composite", "poc:sku:A100-SXM-80GB", "poc:sku:H200-SXM", "poc:sku:B300"],
                  "caption": "Daily on-demand GPU rental indices, rebased to 100 on 2026-08-10."},
        "discovery": {"label": "Milk Road podcast, Nov 2, 2026", "url": MR_CHART},
        "evidence": [
            (MR_CHART, "reported", "supports",
             "Milk Road's Nov 2 episode, with Silicon Data's head of research, reports GPU rental prices rising "
             "sharply while usage-weighted token prices decline, with demand spanning newer Nvidia parts and older "
             "A100s. Reported narrative; not itself a metric series."),
            (POC, "corroborated", "supports",
             "Composite on-demand GPU index 142.28 on 2026-11-05 vs 100 on 2026-08-10 (+10.78% over 30 days); "
             "A100 SXM 80GB at 140.33, H200 SXM at 155.44 and H100 SXM at 124.31."),
            (RAMP, "corroborated", "supports",
             "Blended OpenAI/Anthropic price per million tokens fell to $0.56 from $0.76 (−26.8%), weeks ending "
             "Sep 25 → Oct 23, 2026, as token volume rose 37.1% and total token spend rose 8.9%."),
            (S1, "primary", "supports",
             "Issuer states newer models cut customer cost per task: ~40% (Opus 5.5 vs Opus 5) and ~25% for typical "
             "workloads (Fable 5.1), up to 45% for complex agentic coding."),
            (SD, "corroborated", "context",
             "Silicon Data's public page listed H100 rental at $2.97/hr, B200 $6.70/hr, B300 $7.56/hr and its LLM "
             "token index at $0.86 on Nov 5, 2026."),
            (POC, "corroborated", "challenges",
             "Newest-generation parts are not following the squeeze: B300 on-demand fell 19.1% over 7 days and sits "
             "at 88 vs its August base; B200 fell 9.9% over 7 days."),
            (POC_H100, "corroborated", "challenges",
             "Trackers disagree on level: H100 SXM on-demand median $4.065/hr across 8 providers (spot $2.445, 3 "
             "providers) vs $2.97/hr on Silicon Data's H100 index the same day."),
            (POC, "corroborated", "challenges",
             "Price of Compute's list-price token median ($3.19 per million, 3:1 input:output, 20 models) is "
             "explicitly not usage-weighted — 'falling token prices' depends on the measure used."),
        ],
    },
    {
        "id": "enterprise-ai-spend-compounding",
        "title": "Enterprise AI spend is compounding inside existing customers, not just adding logos",
        "dek": "An issuer filing and a card-spend panel both show deepening usage. The next wedge is helping "
               "enterprises govern, attribute and diversify that spend.",
        "sector": "Enterprise software",
        "themes": ["Enterprise AI adoption", "AI spend management", "Vertical AI"],
        "direction": "Strengthening",
        "what_changed": "Anthropic's S-1 (filed Oct 26, 2026) discloses ~900% net revenue retention as of Sep 30, "
                        "2026, more than 11,900 customers above $100k trailing-twelve-month revenue (vs. more than "
                        "950 a year earlier) and ~250 above $10M. Ramp's AI Index shows 55.9% of sampled US "
                        "businesses paying for AI in September 2026, up 12.1 points year over year, with construction "
                        "(+1.9 pts) and retail (+1.6 pts) rising fastest month over month.",
        "why_now": "Falling cost per task lowers the bar for production workloads, and adoption gains are now coming "
                   "from less-digitized sectors such as construction and retail rather than only technology firms.",
        "market_indication": "Budget is consolidating into a few model vendors while usage per customer expands — "
                             "creating demand for spend visibility, chargeback, evaluation and switching layers, and "
                             "raising vendor-concentration risk for enterprise buyers.",
        "startup_opportunity": "AI spend governance and chargeback per team and workflow; task-level ROI attribution; "
                               "multi-vendor routing and evaluation; vertical agent products for late-adopting "
                               "industries (construction, retail operations).",
        "corporate_buyer": "Finance, FP&A and procurement teams watching AI bills grow inside existing contracts; "
                           "operations leaders in construction, retail and manufacturing moving pilots into "
                           "production.",
        "value_chain": ["Model vendors", "AI spend management", "Vertical AI applications", "Systems integrators"],
        "confidence": "Medium",
        "corroboration": "Corroborated (two independent sources)",
        "confidence_rationale": "An issuer filing and an 85,000+ business card-spend panel point the same way. But "
                                "S-1 metrics are issuer-defined (NRR excludes consumer subscription plans) and come "
                                "from an unusually fast-growing vendor; Ramp measures payment incidence, not workload "
                                "depth.",
        "next_validation": "Read S-1 amendments for NRR methodology and cohort detail; check whether Ramp's next "
                           "monthly release extends gains in construction and retail.",
        "falsifier": "Net revenue retention falls sharply in subsequent filings while Ramp adoption flattens — "
                     "pointing to pilot churn rather than compounding deployment.",
        "thesis_sentence": "Enterprise AI revenue is compounding inside existing customers, creating a new budget line "
                           "that needs governance, attribution and vertical-specific products.",
        "analyst_scores": {"relevance": 5, "impact": 4},
        "match_terms": ["anthropic", "openai", "enterprise", "adoption", "ai spend", "agents", "agentic", "copilot",
                        "s-1", "ipo", "tokens"],
        "match_min": 2,
        "discovery": {"label": "Milk Road, Oct 28, 2026", "url": "https://milkroad.com/ideas/wait-cheaper-ai-is-good-for-anthropic/"},
        "evidence": [
            (S1, "primary", "supports",
             "~900% net revenue retention at Sep 30, 2026; >11,900 customers at $100k+ TTM (vs >950 a year earlier), "
             ">1,900 at $1M+, ~250 at $10M+."),
            (S1, "primary", "supports",
             "Revenue of $16.3B for the six months ended Jun 30, 2026, versus $1.2B in the prior-year period, as "
             "stated in the filing."),
            (RAMP, "corroborated", "supports",
             "55.9% of sampled US businesses paid for AI in September 2026 (+0.6 pts m/m, +12.1 pts y/y); "
             "construction 43.2% (+1.9 pts) and retail 49.9% (+1.6 pts) rose fastest."),
            ("https://milkroad.com/ideas/wait-cheaper-ai-is-good-for-anthropic/", "reported", "challenges",
             "Milk Road notes Ramp data showing business token spend barely grew in August–September even as usage "
             "rose — spend growth can lag usage when prices fall."),
            (S1, "primary", "challenges",
             "The filing reports a $693M operating loss for H1 2026 and $6.2B of total indebtedness at Jun 30, 2026, "
             "partly to fund compute commitments, and flags power and regulatory risk at compute sites."),
        ],
    },
    {
        "id": "seats-to-outcome-pricing",
        "title": "Software and services pricing is moving from seats to credits and outcomes — and filings show the friction",
        "dek": "When agents complete work instead of adding users, seat counts stop tracking value. Issuers are "
               "now disclosing the transition as a risk.",
        "sector": "Enterprise software & services",
        "themes": ["Outcome-based pricing", "Agentic workflows", "Revenue infrastructure"],
        "direction": "Emerging",
        "what_changed": "HubSpot's Q3 10-Q (filed Nov 4, 2026) says its credits-based and outcome-based pricing "
                        "strategies are 'novel and evolving' and have lengthened sales cycles and lowered initial "
                        "contract values. ExlService's Q3 10-Q (filed Oct 27, 2026) reports an industry shift toward "
                        "transaction- and outcome-based pricing and describes moving clients away from FTE-based "
                        "pricing.",
        "why_now": "Agentic products complete tasks rather than add users. Vendors are disclosing the transition in "
                   "risk factors, which means it is material enough to affect revenue timing and forecasting.",
        "market_indication": "Expect a transition period of revenue volatility for incumbents — credit spend may "
                             "substitute for seat spend — and a new requirement for metering, outcome measurement and "
                             "contract terms both sides trust. Headcount-priced services firms face margin pressure "
                             "unless they own the automation.",
        "startup_opportunity": "Usage and outcome metering/billing infrastructure; outcome verification and "
                               "attribution (proving a task was completed and what it saved); pricing analytics for "
                               "vendors in transition; procurement tools comparing seat, credit and outcome contracts.",
        "corporate_buyer": "Procurement and finance teams renegotiating SaaS and BPO contracts; revenue operations at "
                           "software vendors moving to credits; BPO buyers seeking savings-linked pricing.",
        "value_chain": ["Application SaaS", "BPO & IT services", "Billing & metering", "Procurement"],
        "confidence": "Medium",
        "corroboration": "Primary sources (multiple issuers)",
        "confidence_rationale": "Primary disclosures from issuers in different segments (SaaS and BPO) independently "
                                "describe the shift. They describe intent and risk, not quantified adoption; neither "
                                "discloses the share of revenue that is outcome-priced.",
        "next_validation": "Search upcoming 10-K/10-Q filings and earnings materials for a disclosed share of revenue "
                           "under usage/outcome pricing; track HubSpot's next-quarter commentary on credit "
                           "consumption vs seat expansion.",
        "falsifier": "Vendors revert to seat-based packaging, or report negligible credit/outcome revenue after two to "
                     "three quarters, or buyers reject outcome terms over measurement disputes.",
        "thesis_sentence": "As AI agents complete work instead of adding users, pricing is shifting to credits and "
                           "outcomes, creating demand for trusted metering and outcome verification.",
        "analyst_scores": {"relevance": 4, "impact": 4},
        "match_terms": ["outcome-based", "outcome based", "credits-based", "usage-based", "pricing", "seat", "seats",
                        "per seat", "agents", "agentic", "bpo"],
        "match_min": 2,
        "evidence": [
            (HUBS, "primary", "supports",
             "\u201cOur credits-based and outcome-based pricing strategies are novel and evolving\u201d; the changes "
             "have lengthened sales cycles and resulted in lower initial contract values."),
            (EXLS, "primary", "supports",
             "Reports \u201ca shift in the industry pricing models toward transaction-based pricing, outcome-based "
             "pricing\u201d and efforts to move clients from FTE-based pricing; outcome-based fees are tied to clients' "
             "usage or savings."),
            (HUBS, "primary", "challenges",
             "Issuer warns credit spend \u201cmay substitute for, rather than add to, existing seat and hub spend\u201d "
             "and the pricing may not be accepted by customers."),
            (EXLS, "primary", "context",
             "Issuer emphasizes operating efficiency to maintain or improve gross margins as pricing models change."),
        ],
    },
    {
        "id": "memory-substrate-reallocation",
        "title": "Memory and substrate shortages are steering semiconductor profit toward data-center silicon",
        "dek": "Scarce components flow to the highest-margin AI servers. Device refresh cycles and memory-hungry "
               "inference absorb the cost.",
        "sector": "Semiconductors & hardware",
        "themes": ["Supply-chain constraints", "Memory efficiency", "Data-center silicon"],
        "direction": "Strengthening",
        "what_changed": "Intel's Q3 10-Q (filed Oct 30, 2026) shows data-center (DCAI) revenue of $7.32B, up from "
                        "$4.12B a year earlier, with DCAI operating margin at 42% vs 23%, while client (CCPG) revenue "
                        "fell to $8.10B from $8.54B. The filing cites \u201ccurrent industry-wide substrate and memory "
                        "shortages\u201d as a supply-chain risk.",
        "why_now": "AI servers are absorbing memory and advanced-packaging capacity, so constrained components are "
                   "flowing to the highest-margin data-center products and away from PCs.",
        "market_indication": "Component scarcity favors data-center platforms and penalizes device refresh cycles. "
                             "Software that reduces memory footprint and services that extend hardware life gain value "
                             "for as long as the shortage persists.",
        "startup_opportunity": "Memory-efficiency software for inference (KV-cache compression, quantization, "
                               "offloading); enterprise device lifecycle and refurbishment platforms; supply-chain "
                               "risk intelligence for constrained components.",
        "corporate_buyer": "Enterprise IT planning PC and server refreshes amid shortages; infrastructure teams "
                           "sizing inference clusters where memory, not compute, is the binding constraint.",
        "value_chain": ["Memory & substrates", "Server OEMs", "PC OEMs", "Inference software"],
        "confidence": "Medium",
        "corroboration": "Primary source; guidance claims reported only",
        "confidence_rationale": "Segment figures and shortage language come directly from the issuer's 10-Q. "
                                "Forward guidance and PC-market forecasts were reported by a secondary source and not "
                                "yet checked against the earnings 8-K.",
        "next_validation": "Verify Q4 guidance in Intel's Oct 29 earnings 8-K exhibit; read memory makers' next "
                           "filings for pricing and allocation commentary; watch PC OEM guidance.",
        "falsifier": "Memory contract prices fall and Intel's client segment recovers within two quarters, "
                     "indicating a transient rather than structural reallocation.",
        "thesis_sentence": "AI servers are absorbing scarce memory and substrates, shifting semiconductor profit to "
                           "data-center silicon and raising the value of software that does more with less memory.",
        "analyst_scores": {"relevance": 4, "impact": 4},
        "match_terms": ["memory", "dram", "hbm", "substrate", "shortage", "intel", "micron", "pc market", "packaging",
                        "semiconductor", "chips"],
        "match_min": 2,
        "discovery": {"label": "Milk Road, Nov 2, 2026", "url": "https://milkroad.com/ideas/intel-s-worst-day-since-1974/"},
        "evidence": [
            (INTC, "primary", "supports",
             "DCAI revenue $7,318M in Q3 2026 vs $4,117M in Q3 2025 (+78%); DCAI operating margin 42% vs 23%."),
            (INTC, "primary", "supports",
             "Forward-looking risk language cites \u201ccurrent industry-wide substrate and memory shortages\u201d."),
            ("https://milkroad.com/ideas/intel-s-worst-day-since-1974/", "reported", "context",
             "Milk Road reports a weaker Q4 outlook ($15–16B revenue guide, ~38% gross margin), a ~29% one-day share "
             "decline and forecasts of PC-market contraction; not yet checked against the 8-K."),
            (INTC, "primary", "challenges",
             "Client (CCPG) revenue fell only ~5% year over year ($8,097M vs $8,535M) — the device-side impact is so "
             "far modest in reported results."),
        ],
    },
    {
        "id": "powered-compute-as-product",
        "title": "Powered compute capacity is becoming a sellable product outside the hyperscalers",
        "dek": "Aerospace, crypto-infrastructure and energy owners are monetizing power-ready sites as GPU rents rise. "
               "Financing quality and contract duration become the risk.",
        "sector": "AI infrastructure & energy",
        "themes": ["Compute markets", "Power & sites", "Infrastructure finance"],
        "direction": "Emerging",
        "what_changed": "SpaceX's Q3 10-Q (filed Oct 22, 2026) reports 1.7 GW of nameplate compute capacity at Sep 30, "
                        "2026, up from 0.6 GW a year earlier, alongside a new 'Super Intelligence' segment. Milk Road "
                        "reported that Galaxy leased its Helios West Texas campus to CoreWeave and that SpaceX rents "
                        "capacity on short-term contracts that reprice as GPU rents rise.",
        "why_now": "Rising rental prices make short-term capacity leasing lucrative, and energized, permitted sites are "
                   "the scarce input — companies with power, land and capital are monetizing them directly.",
        "market_indication": "Capacity with energized power is pricing like a scarce asset, pulling non-traditional "
                             "owners into compute. Contract duration and financing terms will separate durable "
                             "operators from those exposed to a rent reversal.",
        "startup_opportunity": "Site underwriting and power-availability data; capacity brokerage and short-term "
                               "compute marketplaces; risk and monitoring tools for GPU-backed lending; energy-aware "
                               "workload scheduling.",
        "corporate_buyer": "Enterprises and AI developers seeking capacity outside hyperscaler queues; utilities and "
                           "industrial landowners evaluating data-center conversions.",
        "value_chain": ["Power & sites", "Neoclouds", "Hyperscalers", "GPU finance"],
        "confidence": "Low",
        "corroboration": "Partially corroborated",
        "confidence_rationale": "Capacity growth is a primary disclosure, but nameplate capacity is not utilization, "
                                "and rental terms and revenue attribution come from secondary reporting not yet "
                                "matched to filings.",
        "next_validation": "Verify the Helios lease in Galaxy's Q3 filing; check SpaceX segment disclosures for "
                           "external compute rental revenue vs internal use.",
        "falsifier": "GPU rents fall back as short-term contracts roll off, leaving non-traditional owners with "
                     "under-utilized sites.",
        "thesis_sentence": "Powered compute is becoming a sellable product for non-hyperscalers, making power-ready "
                           "sites and capacity financing the next infrastructure bottleneck.",
        "analyst_scores": {"relevance": 4, "impact": 3},
        "match_terms": ["gigawatt", "gw", "megawatt", "mw", "data center", "power", "spacex", "galaxy", "coreweave",
                        "lease", "capacity", "neocloud"],
        "match_min": 2,
        "discovery": {"label": "Milk Road, Nov 4, 2026", "url": "https://milkroad.com/ideas/why-our-team-keeps-buying-spacex/"},
        "evidence": [
            (SPCX, "primary", "supports",
             "Nameplate compute capacity of 1.7 GW at Sep 30, 2026 vs 0.6 GW at Sep 30, 2025; segments include "
             "Space, Connectivity and Super Intelligence."),
            ("https://milkroad.com/news/glxy-made-323m-now-for-the-hard-part/", "reported", "supports",
             "Milk Road reports Galaxy's Q3 net income of $323M and that its Helios West Texas campus is leased to "
             "CoreWeave."),
            ("https://milkroad.com/ideas/why-our-team-keeps-buying-spacex/", "reported", "supports",
             "Milk Road reports SpaceX rents compute on short-term contracts and cites commentary that GPU rents rose "
             "through October."),
            ("https://milkroad.com/podcast/ai-stocks-just-hit-a-rare-bottom-signal-is-the-worst-over-Anhl5SoXU3Y/",
             "reported", "challenges",
             "Milk Road's Nov 4 episode reports smaller AI-infrastructure firms facing tighter and more expensive "
             "financing."),
            (SPCX, "primary", "challenges",
             "Nameplate capacity is installed capacity, not utilization or contracted external revenue."),
        ],
    },
    {
        "id": "mission-critical-private-5g",
        "title": "Mission-critical private 5G is landing in transport infrastructure, but vendor enterprise revenue is flat",
        "dek": "Large operators are validating cellular for operational systems. Value may accrue to integrators and "
               "managed operators rather than radio vendors.",
        "sector": "Industrial connectivity",
        "themes": ["Private networks", "Critical infrastructure", "Managed services"],
        "direction": "Contested",
        "what_changed": "Ericsson's Q3 2026 report (6-K filed Oct 15, 2026) says it was selected for the first stage "
                        "of Queensland's next-generation rail communications network using mission-critical private 5G "
                        "capabilities. The same report shows Enterprise segment sales down 10% to SEK 4.6b — about +1% "
                        "organically after a divestment.",
        "why_now": "Rail and other critical-infrastructure operators are replacing legacy narrowband radio; "
                   "mission-critical 5G capabilities make cellular viable for operational, not just office, "
                   "connectivity.",
        "market_indication": "Infrastructure contracts validate private 5G for operational use, but flat vendor "
                             "enterprise revenue suggests value accrues to integration, devices and managed operations "
                             "rather than RAN equipment.",
        "startup_opportunity": "Managed private-network operations for multi-site industrial operators; rugged "
                               "devices and applications on mission-critical 5G; ROI measurement (downtime, safety "
                               "incidents) for connectivity investments.",
        "corporate_buyer": "Rail, port, mining and utility operators replacing legacy radio; industrial companies with "
                           "distributed sites that need deterministic connectivity.",
        "value_chain": ["RAN vendors", "Systems integrators", "Industrial devices", "Managed network services"],
        "confidence": "Low",
        "corroboration": "Single primary source",
        "confidence_rationale": "One vendor report with a contract selection but no disclosed value; flat organic "
                                "segment revenue directly challenges near-term acceleration.",
        "next_validation": "Find Queensland procurement records for scope and value; check other RAN vendors' Q3 "
                           "enterprise and private-wireless figures for corroboration.",
        "falsifier": "Competing vendors also report flat private-wireless revenue over the next two quarters with no "
                     "new large operator deployments.",
        "thesis_sentence": "Mission-critical private 5G is being adopted for transport infrastructure, but flat vendor "
                           "revenue suggests value will accrue to integrators and managed operators.",
        "analyst_scores": {"relevance": 3, "impact": 3},
        "match_terms": ["private 5g", "5g", "private network", "private wireless", "ericsson", "nokia", "rail",
                        "industrial", "connectivity", "ran"],
        "match_min": 2,
        "evidence": [
            (ERIC, "primary", "supports",
             "Selected for the first stage of Queensland's next-generation rail communications network with "
             "mission-critical private 5G capabilities."),
            (ERIC, "primary", "context",
             "NTT DOCOMO is deploying Ericsson's RAN Compute platform toward an AI-driven network."),
            (ERIC, "primary", "challenges",
             "Enterprise segment sales fell 10% to SEK 4.6b, about +1% organically after the iconectiv divestment."),
        ],
    },
]

NOTE = {
    "headline": "Compute is getting scarcer as AI output gets cheaper",
    "summary": "The first edition opens six working theses. The common thread: AI demand is broadening into "
               "enterprise budgets and less-digitized industries while physical inputs — GPU-hours, memory, "
               "powered sites — tighten. Each signal separates reported claims, primary disclosures and independent "
               "corroboration from analyst inference, and names what would prove it wrong.",
}

REQUIRED = ("title", "dek", "sector", "themes", "direction", "what_changed", "why_now", "market_indication",
            "startup_opportunity", "corporate_buyer", "value_chain", "confidence", "corroboration",
            "confidence_rationale", "next_validation", "falsifier", "thesis_sentence", "evidence")


def validate_signal(sig: dict[str, Any]) -> list[str]:
    errs = [f"missing {k}" for k in REQUIRED if not sig.get(k)]
    ev = sig.get("evidence") or []
    if not any(e[1] in ("primary", "corroborated") for e in ev):
        errs.append("needs at least one primary or independently corroborated evidence item")
    if not any(e[2] == "challenges" for e in ev):
        errs.append("needs counterevidence (stance=challenges)")
    for e in ev:
        if e[0] not in DOCS:
            errs.append(f"evidence url not registered: {e[0]}")
    return errs


def seed_if_empty(conn: sqlite3.Connection) -> bool:
    if conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]:
        return False
    seed(conn)
    return True


def seed(conn: sqlite3.Connection) -> None:
    for sig in SIGNALS:
        errs = validate_signal(sig)
        if errs:
            raise ValueError(f"{sig['id']}: {errs}")
    with tx(conn):
        for sid, name, kind, home, note in SOURCES:
            conn.execute("INSERT INTO sources(id, name, kind, homepage, access_note) VALUES (?,?,?,?,?) "
                         "ON CONFLICT(id) DO NOTHING", (sid, name, kind, home, note))
        doc_ids: dict[str, int] = {}
        for url, (src, title, stype, pub, event) in DOCS.items():
            item = RawItem(url=url, title=title, source_type=stype, published_at=pub, event_date=event,
                           meta={"verified_for_edition": EDITION_DATE})
            doc_ids[url], _ = upsert_document(conn, item, src, VERIFIED_AT, origin="seed")
        for sig in SIGNALS:
            data = {k: v for k, v in sig.items() if k not in ("id", "evidence")}
            existing = conn.execute("SELECT data FROM signals WHERE id=?", (sig["id"],)).fetchone()
            if existing and loads(existing["data"]) == data:
                continue
            if existing:
                conn.execute("UPDATE signals SET data=?, updated_at=? WHERE id=?", (dumps(data), PUBLISHED_AT, sig["id"]))
            else:
                conn.execute("INSERT INTO signals(id, data, first_published_at, updated_at) VALUES (?,?,?,?)",
                             (sig["id"], dumps(data), PUBLISHED_AT, PUBLISHED_AT))
            conn.execute("INSERT INTO signal_revisions(signal_id, revised_at, reason, data) VALUES (?,?,?,?)",
                         (sig["id"], PUBLISHED_AT, "first edition" if not existing else "seed update", dumps(data)))
            conn.execute("DELETE FROM signal_evidence WHERE signal_id=?", (sig["id"],))
            for pos, (url, claim, stance, statement) in enumerate(sig["evidence"]):
                conn.execute("INSERT INTO signal_evidence(signal_id, document_id, claim_type, stance, statement, position) "
                             "VALUES (?,?,?,?,?,?)", (sig["id"], doc_ids[url], claim, stance, statement, pos))
        conn.execute("INSERT INTO edition_notes(edition_date, headline, summary, created_at) VALUES (?,?,?,?) "
                     "ON CONFLICT(edition_date) DO NOTHING", (EDITION_DATE, NOTE["headline"], NOTE["summary"], PUBLISHED_AT))
        run_id = int(conn.execute("INSERT INTO pipeline_runs(trigger, started_at, finished_at, status, summary) "
                                  "VALUES ('seed', ?, ?, 'seeded', ?)",
                                  (PUBLISHED_AT, PUBLISHED_AT, dumps({"note": "verified first edition loaded"}))
                                  ).lastrowid or 0)
        now = parse_iso(PUBLISHED_AT)
        assert now is not None
        write_snapshot(conn, run_id, now, EDITION_DATE)
    _ = iso  # keep import used for type checkers
