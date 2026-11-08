"""First edition (2026-11-05). Every evidence item below was retrieved and read from its public source
while building this edition; statements are paraphrased or short-quoted, never full-text copies."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from .adapters.base import RawItem
from .db import dumps, loads, tx
from .pipeline import rematch_ingested, upsert_document, write_snapshot
from .timeutil import iso, parse_iso, utcnow
from .urlnorm import canonicalize

EDITION_DATE = "2026-11-05"
PUBLISHED_AT = "2026-11-05T16:00:00Z"
VERIFIED_AT = "2026-11-05T15:45:00Z"  # verification window for first-edition retrievals: 15:30–16:00 UTC
EVIDENCE_UPDATED_AT = "2026-11-08T13:40:00Z"  # primary filings retrieved and read for theses re-reviewed in v6
REVISED_AT = "2026-11-08T14:00:00Z"  # editorial revision v6: powered compute re-reviewed against Galaxy and IREN filings
CONTENT_VERSION = 6

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
    "https://www.sec.gov/Archives/edgar/data/1859392/000185939226000108/glxy-20260930xpressrelease.htm":
        ("sec_edgar", "Galaxy Digital Inc. — Q3 2026 results (8-K, Ex. 99.1) filed 2026-10-27", "regulatory_filing",
         "2026-10-27", "2026-09-30"),
    "https://www.sec.gov/Archives/edgar/data/1878848/000187884826000065/irenreportsq1-fy27result.htm":
        ("sec_edgar", "IREN Ltd — Q1 FY27 results (8-K, Ex. 99.1) filed 2026-11-05", "regulatory_filing",
         "2026-11-05", "2026-09-30"),
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
GLXY = "https://www.sec.gov/Archives/edgar/data/1859392/000185939226000108/glxy-20260930xpressrelease.htm"
IREN = "https://www.sec.gov/Archives/edgar/data/1878848/000187884826000065/irenreportsq1-fy27result.htm"

# (url, claim_type, stance, statement)
Ev = tuple[str, str, str, str]
ROLES = ("buyer", "benefits", "pressure")
CRYPTO = ["ethereum", "bitcoin", "crypto", "cryptocurrency", "defi", "stablecoin", "stablecoins", "solana", "altcoin",
          "altcoins", "memecoin", "xrp", "nft"]

SIGNALS: list[dict[str, Any]] = [
    {
        "id": "gpu-rent-vs-token-deflation",
        "content_version": CONTENT_VERSION,
        "title": "Output per GPU-hour, not list price, increasingly decides AI costs as older and mid-generation GPU rents rise",
        "brief": ["A100 and H200 rents are up 40–55% since August (Price of Compute)", "Token prices businesses paid fell 27% in four weeks (Ramp)", "Cost per useful task now matters more than a GPU's list price"],
        "dek": "Renting A100, H100 and H200 GPUs has become more expensive since August, while the average price "
               "businesses paid per AI token fell. The newest GPUs got cheaper.",
        "takeaway": "Since mid-August, on-demand rental prices for A100, H100 and H200 GPUs have risen on Price of "
                    "Compute's indices. Over a recent four-week window, the blended price businesses paid OpenAI and "
                    "Anthropic per million tokens (a token is a small unit of model text) fell 26.8% on Ramp's data. "
                    "If this gap persists, the cost of an AI workload depends more on how much useful work each "
                    "GPU-hour produces than on list prices.",
        "caveats": [
            "The two measures are not directly comparable: the rental indices cover about three months, the token "
            "figure four weeks; workload and model mix differ; and neither adjusts for output quality.",
            "Prices are rising for older and mid-generation GPUs only. B300 sits below its August level and B200 fell "
            "9.9% in a week, so this does not show that all compute is getting scarcer.",
            "A margin squeeze for AI software companies is an inference. It has not been shown with comparable unit "
            "economics.",
        ],
        "sector": "AI infrastructure",
        "themes": ["Compute economics", "Inference efficiency", "Compute markets"],
        "direction": "Strengthening",
        "what_changed": "Price of Compute's composite on-demand GPU index stood at 142.28 on Nov 5 (100 = Aug 10), with "
                        "A100 SXM 80GB at 140, H200 SXM at 155 and H100 SXM at 124. Ramp's card-spend panel shows the "
                        "blended OpenAI/Anthropic price per million tokens fell 26.8% (weeks ending Sep 25 to Oct 23) "
                        "while token volume rose 37.1%.",
        "changed_points": [
            "Price of Compute composite on-demand GPU index: 142.28 on Nov 5 (Aug 10 = 100). A100 SXM 80GB 140, "
            "H200 SXM 155, H100 SXM 124.",
            "Newest parts moved the other way: B300 at 88 versus its August base; B200 down 9.9% in seven days.",
            "Ramp: blended OpenAI/Anthropic price per million tokens $0.76 → $0.56 (−26.8%), weeks ending Sep 25 → "
            "Oct 23. Token volume +37.1%; token spend +8.9%.",
            "Anthropic's S-1 says newer models cut customer cost per task by roughly 25–40%.",
        ],
        "why_now": "Buyers appear to be renting older capacity rather than waiting for newer supply, while model "
                   "vendors keep lowering the cost of a unit of output. Both moves are recent; the rental indices "
                   "only begin in August 2026.",
        "market_indication": "The cost of an AI workload increasingly depends on throughput per GPU-hour and on the "
                             "choice between owned, rented and API capacity. Whether this compresses anyone's margins "
                             "depends on contract terms that are not public.",
        "audiences": [
            {"segment": "Enterprises", "role": "buyer",
             "who": "CIOs, heads of infrastructure and FP&A teams with AI workloads in production.",
             "impact": "Rented or reserved GPU capacity may cost more while per-token API prices fall, which can "
                       "change the build, rent or API decision.",
             "action": "Compare cost per completed task for current workloads across owned hardware, rented GPUs and "
                       "model APIs at matched quality.",
             "trigger": "The composite index stays above ~130 over the next refreshes, or a reserved-capacity renewal "
                        "is quoted above the prior contract."},
            {"segment": "SMBs", "role": "benefits",
             "who": "Owners and operations leads who buy packaged AI tools rather than infrastructure.",
             "impact": "Falling token prices can make AI tools cheaper per task, but vendors may not pass savings on.",
             "action": "Judge AI tools by staff hours saved or added revenue per month, not by headline price.",
             "trigger": "Vendors cut prices or raise usage limits on plans you already pay for."},
            {"segment": "Software companies", "role": "pressure",
             "who": "Founders, CFOs and pricing leads at AI application companies.",
             "impact": "Revenue per token may fall with API prices while any rented GPU capacity costs more, which "
                       "would squeeze margins on fixed-price plans.",
             "action": "Model gross margin under both trends and split serving cost between rented GPUs and APIs.",
             "trigger": "Public AI software companies attribute gross-margin declines to inference or hosting costs."},
            {"segment": "Service providers", "role": "benefits",
             "who": "IT consultancies, managed service providers and cloud resellers.",
             "impact": "Clients need help choosing between capacity options and measuring cost per task.",
             "action": "Offer a cost-per-task assessment that benchmarks a client's workloads across APIs and "
                       "rented GPUs.",
             "trigger": "Client RFPs start asking for cost-per-task or capacity-procurement advice."},
        ],
        "implications": [
            {"trend": "Older GPU rents rising while token prices fall",
             "problem": "Budgets set on last quarter's prices drift, and the cheapest option per task changes month "
                        "to month.",
             "buyer": "Enterprise infrastructure and FP&A teams",
             "solution": "Cost-per-task benchmarking and routing workloads across APIs and rented capacity",
             "investigate": "Inference-optimization and model-routing software; GPU marketplaces and procurement "
                            "platforms (categories)"},
            {"trend": "Public GPU price indices now exist (Price of Compute, Silicon Data)",
             "problem": "No standard way to budget for or hedge rented compute",
             "buyer": "Finance teams at AI-heavy companies and GPU cloud providers",
             "solution": "Index-linked capacity contracts and procurement analytics",
             "investigate": "Compute procurement and index-linked contracting tools (category)"},
        ],
        "card_implication": "Re-check the build, rent or API decision on cost per completed task.",
        "customer_validation": "Interview 5–10 enterprise infrastructure or FinOps leads: has a GPU capacity renewal "
                               "or quote risen since August, and do they measure cost per completed task?",
        "view_triggers": [
            "The composite index falls back toward 100 while token volume growth stalls.",
            "Silicon Data's H100 index diverges from Price of Compute's for several weeks.",
            "Ramp's next releases show blended token prices flat or rising.",
        ],
        "value_chain": ["GPU rental & neoclouds", "Inference serving software", "Model APIs",
                        "Enterprise AI budgets", "Compute indices & derivatives"],
        "confidence": "Medium",
        "corroboration": "Corroborated (direction)",
        "confidence_rationale": "The direction is corroborated by two independent rental trackers and a large "
                                "card-spend dataset. Levels differ between trackers (H100 on-demand $4.07/hr median vs "
                                "$2.97/hr the same day), the index history is under three months, and the token measure "
                                "covers two vendors. Single-SKU series can be noisy (A100 PCIe 80GB alternates between "
                                "~117 and ~212), so this thesis relies on the composite and steadier series.",
        "next_validation": "Check whether the composite holds above ~130 over the next refreshes; compare Ramp's next "
                           "release for spend versus volume; check that Silicon Data's H100 index moves the same way.",
        "falsifier": "Rental indices revert to their August base while token volume growth stalls, which would point "
                     "to a short-lived capacity squeeze rather than a durable gap.",
        "thesis_sentence": "Rental prices for older and mid-generation GPUs are rising while blended token prices "
                           "fall, so the cost of AI work increasingly depends on how much useful work each GPU-hour "
                           "produces.",
        "evidence_reviewed_at": VERIFIED_AT,
        "analyst_scores": {"relevance": 5, "impact": 4},
        "match": {"anchors": ["gpu", "gpus", "h100", "a100", "h200", "b200", "b300", "neocloud", "coreweave", "nebius",
                              "gpu rental", "compute prices"],
                  "context": ["rental", "rent", "price", "prices", "pricing", "token", "tokens", "inference", "compute",
                              "capacity", "nvidia", "shortage"],
                  "exclude": CRYPTO, "min_terms": 2, "topic": "GPU rental or token pricing"},
        "chart": {"series": ["poc:composite", "poc:sku:A100-SXM-80GB", "poc:sku:H200-SXM", "poc:sku:B300"],
                  "caption": "Daily on-demand GPU rental indices, rebased to 100 on 2026-08-10.",
                  "title": "GPU rental price indices since August 2026",
                  "insight": "Older and mid-generation GPUs (A100, H200) rose most; the newest B300 fell below its August level."},
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
             "Newest-generation parts are moving the other way: B300 on-demand fell 19.1% over 7 days and sits at 88 "
             "vs its August base; B200 fell 9.9% over 7 days."),
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
        "content_version": CONTENT_VERSION,
        "title": "Enterprise AI spend compounds inside existing customers, creating a budget line that needs governance",
        "brief": ["Anthropic: 950 → 11,900+ customers paying $100k+ a year", "~900% net revenue retention: existing customers drive growth", "56% of sampled US businesses pay for AI (Ramp), up 12 pts in a year"],
        "dek": "An AI vendor's filing and a card-spend panel both show usage growing within accounts, with spend "
               "concentrated in a few model vendors.",
        "takeaway": "Anthropic's S-1 reports about 900% net revenue retention (revenue this year from last year's "
                    "customers, relative to what they paid before) and over 11,900 customers paying $100k+ a year, up "
                    "from about 950. Ramp's panel shows 55.9% of sampled US businesses paying for AI, with construction "
                    "and retail rising fastest. Spend is growing inside accounts and spreading to less-digitized "
                    "industries, which raises governance and vendor-concentration questions.",
        "caveats": [
            "The S-1 metrics are issuer-defined and come from one unusually fast-growing vendor; net revenue "
            "retention excludes consumer plans.",
            "Ramp measures whether a business pays for AI, not how deeply it uses it.",
        ],
        "sector": "Enterprise software & services",
        "themes": ["Enterprise AI adoption", "AI spend management", "Vertical AI"],
        "direction": "Strengthening",
        "what_changed": "Anthropic's S-1 (filed Oct 26, 2026) discloses ~900% net revenue retention as of Sep 30, "
                        "2026 and more than 11,900 customers above $100k trailing-twelve-month revenue, up from more "
                        "than 950 a year earlier. Ramp's AI Index shows 55.9% of sampled US businesses paying for AI in "
                        "September 2026, up 12.1 points year over year.",
        "changed_points": [
            "Anthropic S-1: ~900% net revenue retention at Sep 30, 2026; >11,900 customers at $100k+ (vs >950 a year "
            "earlier); ~250 at $10M+.",
            "Anthropic S-1: $16.3B revenue in H1 2026 vs $1.2B a year earlier.",
            "Ramp AI Index: 55.9% of sampled US businesses paid for AI in September (+12.1 pts y/y). Construction "
            "43.2% (+1.9 pts m/m) and retail 49.9% (+1.6 pts) rose fastest.",
        ],
        "why_now": "Lower cost per task makes production workloads easier to justify, and adoption gains now come from "
                   "construction and retail rather than only technology firms.",
        "market_indication": "Budget is concentrating in a few model vendors while usage per customer expands. That "
                             "creates demand for spend visibility, chargeback and switching options, and raises "
                             "vendor-concentration risk for buyers.",
        "audiences": [
            {"segment": "Enterprises", "role": "buyer",
             "who": "CFOs, FP&A and procurement teams, and CIOs who own AI vendor contracts.",
             "impact": "AI bills can grow inside existing contracts without new approvals, and spend concentrates on "
                       "one or two vendors.",
             "action": "Inventory AI spend by team and workflow; check contracts for usage commitments and switching "
                       "costs.",
             "trigger": "AI line items grow faster than headcount or revenue for two consecutive quarters."},
            {"segment": "SMBs", "role": "pressure",
             "who": "Owners and operations managers in construction, retail and other late-adopting sectors.",
             "impact": "Peers are adopting AI tools; lagging can become a cost or response-time disadvantage.",
             "action": "Pilot one AI tool on a measurable task (quotes, scheduling, customer replies) and track hours "
                       "saved.",
             "trigger": "Ramp's adoption rate for your sector passes half of businesses (construction 43.2%, retail "
                        "49.9% in September)."},
            {"segment": "Software companies", "role": "benefits",
             "who": "Product and finance leaders at AI-enabled software vendors.",
             "impact": "Customers expand usage after the first purchase, so revenue depends on usage growth and on "
                       "the model costs you pass through.",
             "action": "Report per-account usage expansion separately from new-customer growth, and model your "
                       "dependence on one model vendor.",
             "trigger": "Your main model vendor changes pricing or usage terms."},
            {"segment": "Service providers", "role": "benefits",
             "who": "Systems integrators and AI consultancies.",
             "impact": "Moving pilots into production in less-digitized industries needs integration and change "
                       "management.",
             "action": "Build repeatable deployment packages for construction or retail operations.",
             "trigger": "Client requests shift from pilots to production rollouts."},
        ],
        "implications": [
            {"trend": "AI spend expanding within existing customers",
             "problem": "Little visibility into which teams and workflows drive AI cost or value",
             "buyer": "Enterprise finance and procurement",
             "solution": "AI spend governance, chargeback and task-level ROI attribution",
             "investigate": "AI spend-management and FinOps-for-AI tools (category)"},
            {"trend": "Adoption rising fastest in construction and retail",
             "problem": "General-purpose AI tools fit field and store operations poorly",
             "buyer": "Operations leaders in construction and retail",
             "solution": "Vertical AI for estimating, scheduling and store operations",
             "investigate": "Vertical AI products for construction and retail operations (category)"},
        ],
        "card_implication": "Finance teams need AI spend visibility by team before it compounds further.",
        "customer_validation": "Ask 5–10 enterprise finance or procurement leads whether AI spend is tracked by team "
                               "and whether any AI contract auto-expanded in the past two quarters.",
        "view_triggers": [
            "Net revenue retention falls sharply in S-1 amendments or later filings.",
            "Ramp adoption flattens for two months, especially in construction and retail.",
            "Token spend keeps lagging usage, suggesting price cuts offset volume.",
        ],
        "value_chain": ["Model vendors", "AI spend management", "Vertical AI applications", "Systems integrators"],
        "confidence": "Medium",
        "corroboration": "Corroborated (two independent sources)",
        "confidence_rationale": "An issuer filing and an 85,000+ business card-spend panel point the same way. But "
                                "S-1 metrics are issuer-defined (NRR excludes consumer subscription plans) and come "
                                "from an unusually fast-growing vendor; Ramp measures payment incidence, not workload "
                                "depth.",
        "next_validation": "Read S-1 amendments for NRR methodology and cohort detail; check whether Ramp's next "
                           "monthly release extends gains in construction and retail.",
        "falsifier": "Net revenue retention falls sharply in subsequent filings while Ramp adoption flattens, which "
                     "would point to pilot churn rather than compounding deployment.",
        "thesis_sentence": "Enterprise AI revenue is deepening inside existing customers, creating a fast-growing "
                           "budget line that needs governance, attribution and industry-specific products.",
        "evidence_reviewed_at": VERIFIED_AT,
        "analyst_scores": {"relevance": 5, "impact": 4},
        "match": {"anchors": ["anthropic", "openai", "enterprise ai", "ai spend", "ai spending", "ai adoption",
                              "ai budget", "ai budgets", "copilot", "net revenue retention"],
                  "context": ["enterprise", "enterprises", "adoption", "spend", "spending", "customers", "revenue",
                              "businesses", "budget", "s-1", "ipo", "contracts"],
                  "exclude": CRYPTO, "min_terms": 2, "topic": "enterprise AI spending"},
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
        "content_version": CONTENT_VERSION,
        "title": "Credit and outcome pricing will need trusted metering before buyers accept it",
        "brief": ["HubSpot: credit and outcome pricing lengthened sales cycles", "ExlService: moving clients off per-person fees", "Neither discloses how much revenue is priced this way yet"],
        "dek": "HubSpot says credit and outcome pricing has lengthened sales cycles; ExlService describes moving "
               "clients off headcount-based fees.",
        "takeaway": "HubSpot's and ExlService's latest quarterly filings both describe moving from pricing per user or "
                    "per person to pricing by credits, transactions or outcomes. HubSpot says the change has lengthened "
                    "sales cycles and lowered initial contract values. Neither discloses how much revenue is priced "
                    "this way yet.",
        "caveats": [
            "Two issuers describing intent and risk; neither quantifies revenue under the new models.",
            "HubSpot warns credit spend may replace rather than add to seat spend.",
        ],
        "sector": "Enterprise software & services",
        "themes": ["Outcome-based pricing", "Agentic workflows", "Revenue infrastructure"],
        "direction": "Emerging",
        "what_changed": "HubSpot's Q3 10-Q (filed Nov 4, 2026) says its credits-based and outcome-based pricing "
                        "strategies are 'novel and evolving' and have lengthened sales cycles and lowered initial "
                        "contract values. ExlService's Q3 10-Q (filed Oct 27, 2026) reports an industry shift toward "
                        "transaction- and outcome-based pricing and describes moving clients away from FTE-based "
                        "pricing.",
        "changed_points": [
            "HubSpot 10-Q (Nov 4): credits-based and outcome-based pricing are \u201cnovel and evolving\u201d; the "
            "changes lengthened sales cycles and lowered initial contract values.",
            "ExlService 10-Q (Oct 27): industry pricing is shifting toward transaction- and outcome-based models; the "
            "firm is moving clients off FTE (per-person) pricing.",
        ],
        "why_now": "AI agents complete tasks rather than add users, so seat counts track value less well. Both "
                   "companies now discuss the transition in risk disclosures, which suggests it is material to revenue "
                   "timing.",
        "market_indication": "Expect a transition period of less predictable revenue for incumbents, and a new need "
                             "for metering, outcome measurement and contract terms both sides trust. Firms that bill "
                             "per person face margin pressure unless they own the automation.",
        "audiences": [
            {"segment": "Enterprises", "role": "buyer",
             "who": "Procurement, finance and vendor-management teams renewing software and outsourcing contracts.",
             "impact": "Credit- or outcome-priced contracts change how costs scale and require agreed measurement.",
             "action": "Before renewal, ask vendors for credit or outcome options and define how a completed outcome "
                       "is measured.",
             "trigger": "A major vendor proposes moving your contract to credit or outcome terms at renewal."},
            {"segment": "SMBs", "role": "pressure",
             "who": "Small and mid-sized businesses on usage-metered software plans.",
             "impact": "Bills may depend on credits consumed rather than users, which makes monthly costs less "
                       "predictable.",
             "action": "Find which features consume credits and set usage alerts or caps.",
             "trigger": "Your software vendor adds credit-metered features to your plan."},
            {"segment": "Software companies", "role": "pressure",
             "who": "CFOs, pricing and revenue-operations leaders at software vendors.",
             "impact": "Moving off seats can lengthen sales cycles and lower first-year contract values, as HubSpot "
                       "reports, making revenue harder to forecast.",
             "action": "Pilot credit or outcome pricing with one customer cohort and compare sales-cycle length and "
                       "expansion against seat deals.",
             "trigger": "Peers start disclosing the share of revenue under usage or outcome pricing."},
            {"segment": "Service providers", "role": "pressure",
             "who": "Outsourcing (BPO) and IT-services firms that bill per person.",
             "impact": "Automation reduces billable headcount; outcome fees tie revenue to client savings.",
             "action": "Identify contracts where automated work could be priced per transaction or on savings, as "
                       "ExlService describes.",
             "trigger": "Clients request savings-linked terms in RFPs."},
        ],
        "implications": [
            {"trend": "Pricing moving to credits and outcomes",
             "problem": "Vendors and buyers lack a trusted way to meter usage and verify outcomes",
             "buyer": "Revenue operations at software vendors; procurement at enterprises",
             "solution": "Usage and outcome metering, billing and verification",
             "investigate": "Usage-based billing and outcome-verification infrastructure (category)"},
            {"trend": "Outsourcing moving off per-person pricing",
             "problem": "Outcome contracts need agreed baselines and savings measurement",
             "buyer": "Outsourcing buyers and providers",
             "solution": "Contract analytics comparing seat, credit and outcome terms",
             "investigate": "Procurement and contract-analytics tools for AI-era pricing (category)"},
        ],
        "card_implication": "Define how outcomes are measured before accepting credit or outcome terms.",
        "customer_validation": "Ask 5 software finance or revenue-operations leads whether they have launched credit "
                               "or outcome pricing and what happened to sales-cycle length.",
        "view_triggers": [
            "Vendors revert to seat-based packaging.",
            "Credit or outcome revenue stays negligible after two to three quarters.",
            "Buyers reject outcome terms over measurement disputes.",
        ],
        "value_chain": ["Application SaaS", "BPO & IT services", "Billing & metering", "Procurement"],
        "confidence": "Medium",
        "corroboration": "Primary sources (multiple issuers)",
        "confidence_rationale": "Primary disclosures from issuers in different segments (software and outsourcing) "
                                "independently describe the shift. They describe intent and risk, not quantified "
                                "adoption; neither discloses the share of revenue that is outcome-priced.",
        "next_validation": "Search upcoming 10-K/10-Q filings and earnings materials for a disclosed share of revenue "
                           "under usage or outcome pricing; track HubSpot's next-quarter commentary on credit "
                           "consumption versus seat expansion.",
        "falsifier": "Vendors revert to seat-based packaging, report negligible credit or outcome revenue after two "
                     "to three quarters, or buyers reject outcome terms over measurement disputes.",
        "thesis_sentence": "As AI agents complete work instead of adding users, software and services pricing is "
                           "moving to credits and outcomes, creating demand for trusted metering and outcome "
                           "verification.",
        "evidence_reviewed_at": VERIFIED_AT,
        "analyst_scores": {"relevance": 4, "impact": 4},
        "match": {"anchors": ["outcome-based", "outcome based", "credits-based", "usage-based", "per-seat", "per seat",
                              "seat-based", "bpo", "hubspot", "exlservice"],
                  "context": ["pricing", "price", "agents", "agentic", "saas", "software", "contracts", "revenue",
                              "seats", "outsourcing"],
                  "exclude": CRYPTO, "min_terms": 2, "topic": "software and services pricing models"},
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
        "content_version": CONTENT_VERSION,
        "title": "Scarce memory and substrates are flowing to AI servers, favoring data-center chips over PCs",
        "brief": ["Intel data-center revenue +78% while PC chips fell ~5%", "Data-center operating margin rose from 23% to 42%", "Intel flags industry-wide memory and substrate shortages"],
        "dek": "Constrained components appear to be flowing to higher-margin AI servers; the PC-side impact on Intel "
               "is so far modest.",
        "takeaway": "Intel's Q3 filing shows data-center revenue up 78% year over year, with that segment's operating "
                    "margin rising from 23% to 42%, while PC-chip revenue fell about 5%. The filing names "
                    "industry-wide memory and substrate (chip-packaging material) shortages as a risk. This is one "
                    "company's data; an industry-wide shift needs memory makers' and hardware makers' figures.",
        "caveats": [
            "Single issuer; an industry-wide reallocation is an inference.",
            "Q4 guidance and PC-market forecasts come from a newsletter and are not yet checked against Intel's 8-K.",
        ],
        "sector": "Semiconductors & hardware",
        "themes": ["Supply-chain constraints", "Memory efficiency", "Data-center silicon"],
        "direction": "Strengthening",
        "what_changed": "Intel's Q3 10-Q (filed Oct 30, 2026) shows data-center (DCAI) revenue of $7.32B, up from "
                        "$4.12B a year earlier, with DCAI operating margin at 42% vs 23%, while client (CCPG) revenue "
                        "fell to $8.10B from $8.54B. The filing cites \u201ccurrent industry-wide substrate and memory "
                        "shortages\u201d as a supply-chain risk.",
        "changed_points": [
            "Intel data-center (DCAI) revenue $7.32B in Q3 2026 vs $4.12B a year earlier (+78%); operating margin "
            "42% vs 23%.",
            "Intel PC-chip (CCPG) revenue $8.10B vs $8.54B (about −5%).",
            "Risk language cites \u201ccurrent industry-wide substrate and memory shortages\u201d.",
        ],
        "why_now": "AI servers are absorbing memory and advanced-packaging capacity, so scarce components may be "
                   "flowing to the highest-margin data-center products ahead of PCs.",
        "market_indication": "If the shortage persists, component scarcity favors data-center platforms and delays "
                             "device refreshes. Software that reduces memory use and services that extend hardware "
                             "life gain value while it lasts.",
        "audiences": [
            {"segment": "Enterprises", "role": "pressure",
             "who": "IT and infrastructure leaders planning PC and server refreshes.",
             "impact": "Shortages can raise prices and lengthen lead times for servers and PCs.",
             "action": "Secure refresh quotes and lead times early; consider extending device life where performance "
                       "allows.",
             "trigger": "Hardware vendors raise quotes or extend lead times, citing memory."},
            {"segment": "Software companies", "role": "benefits",
             "who": "Teams building or running AI inference.",
             "impact": "When memory is the binding constraint, software that uses less memory per request lowers cost.",
             "action": "Measure memory use per request, not just compute, and test compression or quantization "
                       "(storing model numbers at lower precision).",
             "trigger": "Memory makers report rising contract prices."},
            {"segment": "Service providers", "role": "benefits",
             "who": "Device-lifecycle, refurbishment and IT asset-management providers.",
             "impact": "Longer refresh cycles raise demand for repair, refurbishment and extended support.",
             "action": "Offer refresh-deferral assessments to enterprise clients.",
             "trigger": "PC makers guide shipments down, citing component shortages."},
        ],
        "implications": [
            {"trend": "Scarce memory and substrates",
             "problem": "AI inference clusters hit memory limits before compute limits",
             "buyer": "AI infrastructure teams",
             "solution": "Memory-efficient inference (cache compression, quantization, offloading)",
             "investigate": "Inference memory-optimization software (category)"},
            {"trend": "Device refreshes under supply pressure",
             "problem": "Enterprises must run older fleets for longer",
             "buyer": "Enterprise IT asset managers",
             "solution": "Device lifecycle, refurbishment and extended-support services",
             "investigate": "Enterprise device-lifecycle and refurbishment providers (category)"},
        ],
        "card_implication": "IT teams planning refreshes should secure quotes and lead times early.",
        "customer_validation": "Ask enterprise IT buyers and resellers whether server or PC quotes and lead times "
                               "changed in the past quarter, and why.",
        "view_triggers": [
            "Memory contract prices fall within two quarters.",
            "Intel's PC segment recovers while data-center margin normalizes.",
            "Memory makers' filings do not mention allocation to AI servers.",
        ],
        "value_chain": ["Memory & substrates", "Server OEMs", "PC OEMs", "Inference software"],
        "confidence": "Medium",
        "corroboration": "Primary source; guidance claims reported only",
        "confidence_rationale": "Segment figures and shortage language come directly from the issuer's 10-Q. "
                                "Forward guidance and PC-market forecasts were reported by a secondary source and not "
                                "yet checked against the earnings 8-K.",
        "next_validation": "Verify Q4 guidance in Intel's Oct 29 earnings 8-K exhibit; read memory makers' next "
                           "filings for pricing and allocation commentary; watch PC makers' guidance.",
        "falsifier": "Memory contract prices fall and Intel's client segment recovers within two quarters, "
                     "indicating a transient rather than structural reallocation.",
        "thesis_sentence": "AI servers are absorbing scarce memory and substrates, favoring data-center silicon and "
                           "raising the value of software that does more with less memory.",
        "evidence_reviewed_at": VERIFIED_AT,
        "analyst_scores": {"relevance": 4, "impact": 4},
        "match": {"anchors": ["dram", "hbm", "nand", "substrate", "substrates", "memory shortage", "memory prices",
                              "micron", "sk hynix", "intel"],
                  "context": ["memory", "shortage", "shortages", "chips", "chip", "semiconductor", "pc", "pcs",
                              "data center", "supply", "prices", "earnings"],
                  "exclude": CRYPTO, "min_terms": 2, "topic": "memory and chip supply"},
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
        "content_version": CONTENT_VERSION,
        "title": "Power-ready sites are becoming a sellable compute product outside the hyperscalers",
        "brief": ["Galaxy has delivered all 133 MW at its Texas Helios campus to CoreWeave", "IREN's contract prices rose 11–12%; a new five-year deal is ~$22M per MW", "Delivery timing and unleased capacity are the risks"],
        "dek": "Galaxy and IREN filings show leased, revenue-earning AI capacity at rising contract prices. "
               "Delivery delays and capacity still without a tenant are the risks.",
        "takeaway": "Galaxy's Q3 results report all 133 MW of critical IT load at its Helios campus in West Texas "
                    "delivered to CoreWeave under a lease. IREN's Q1 FY27 results report contracted prices up 11% on "
                    "3-year and 12% on 5-year deals, and a new five-year contract at about $22 million of annual "
                    "revenue per IT megawatt. SpaceX reports 1.7 GW of nameplate compute capacity, up from 0.6 GW. "
                    "Power-ready sites are selling as compute capacity; delivery timing and financing are the risks.",
        "caveats": [
            "Nameplate capacity is not utilization or external revenue; SpaceX does not disclose outside rental revenue.",
            "IREN's revenue-per-megawatt figures are company estimates based on its own power-consumption assumptions.",
            "IREN's $4B ARR target slipped from year-end 2026 to January 2027 and may extend to February; Galaxy has "
            "830 MW at Helios II not yet under lease.",
        ],
        "sector": "AI infrastructure",
        "themes": ["Compute markets", "Power & sites", "Infrastructure finance"],
        "direction": "Strengthening",
        "what_changed": "Galaxy's Q3 results (8-K, Oct 27, 2026) report all 133 MW of Helios I, Phase I critical IT "
                        "load delivered to CoreWeave and $69M of data-center adjusted EBITDA in the first full quarter "
                        "of operations. IREN's Q1 FY27 results (8-K, Nov 5, 2026) report AI Cloud revenue of $200M, up "
                        "from $71M the prior quarter, and contracted pricing up 11% (3-year) and 12% (5-year). SpaceX's "
                        "Q3 10-Q reports 1.7 GW of nameplate compute capacity, up from 0.6 GW a year earlier.",
        "changed_points": [
            "Galaxy 8-K: all 133 MW of Helios I, Phase I critical IT load delivered to CoreWeave; Q3 data-center "
            "adjusted EBITDA $69M.",
            "IREN 8-K: AI Cloud revenue $200M vs $71M the prior quarter; contracted pricing +11% on 3-year and +12% on "
            "5-year deals.",
            "IREN 8-K, after quarter-end: about $22M per IT-MW on a five-year contract with 90% of GPU capex prepaid, "
            "and a short-term contract at $40M per IT-MW.",
            "SpaceX 10-Q: 1.7 GW nameplate compute capacity at Sep 30, 2026 vs 0.6 GW a year earlier.",
        ],
        "why_now": "Rising GPU rents and customer prepayments make leasing capacity attractive, and energized, permitted "
                   "sites are scarce, so companies that already have power, land and capital can monetize them.",
        "market_indication": "Capacity with energized power is pricing like a scarce asset and pulling in "
                             "non-traditional owners. Contract length and financing terms will separate durable "
                             "operators from those exposed to a fall in rents.",
        "audiences": [
            {"segment": "Enterprises", "role": "buyer",
             "who": "AI and infrastructure leaders who need capacity outside hyperscaler queues.",
             "impact": "More non-traditional providers may offer capacity, often on short contracts that reprice.",
             "action": "Evaluate alternative providers on contract length, repricing terms and power reliability, not "
                       "only price.",
             "trigger": "Alternative providers publish pricing, or hyperscaler waitlists lengthen."},
            {"segment": "Infrastructure & energy owners", "role": "benefits",
             "who": "Utilities, industrial landowners and site developers with power and permits.",
             "impact": "Energized, permitted land may be monetizable as compute capacity.",
             "action": "Assess which sites have deliverable power and what conversion would cost.",
             "trigger": "Comparable sites lease to AI tenants on disclosed terms."},
            {"segment": "Lenders & investors", "role": "pressure",
             "who": "Lenders and investors financing GPU and site build-outs.",
             "impact": "Short contracts, and falling rents for the newest GPUs, raise refinancing risk.",
             "action": "Stress-test GPU-backed loans against a rent decline like B300's since August.",
             "trigger": "Smaller AI-infrastructure firms report tighter or costlier financing."},
        ],
        "implications": [
            {"trend": "Non-hyperscalers monetizing powered sites",
             "problem": "Hard to know which sites can deliver power on schedule",
             "buyer": "Developers, utilities and capacity buyers",
             "solution": "Site underwriting and power-availability data",
             "investigate": "Power-availability data and site-underwriting providers (category)"},
            {"trend": "Short-term capacity contracts",
             "problem": "Lenders cannot easily monitor GPU utilization and pricing behind their collateral",
             "buyer": "GPU-backed lenders",
             "solution": "Collateral monitoring and risk tools for compute finance",
             "investigate": "Compute-finance risk and monitoring tools (category)"},
        ],
        "card_implication": "Capacity buyers should weigh contract length and repricing terms, not just price.",
        "customer_validation": "Ask 3–5 capacity buyers whether they have contracted with non-hyperscaler providers, on "
                               "what term length, and whether they prepaid any GPU capex.",
        "view_triggers": [
            "GPU rents fall as short-term contracts roll off.",
            "SpaceX segment disclosures show capacity is mostly for internal use.",
            "Financing for smaller AI-infrastructure firms tightens further.",
            "IREN's $4B ARR is not operational by the end of February 2027.",
        ],
        "value_chain": ["Power & sites", "Neoclouds", "Hyperscalers", "GPU finance"],
        "confidence": "Medium",
        "corroboration": "Primary sources (multiple issuers)",
        "confidence_rationale": "Leased, revenue-earning capacity and rising contract prices are primary disclosures "
                                "from two operators, but per-megawatt figures are company estimates, IREN's delivery "
                                "has slipped, and SpaceX does not disclose external rental revenue.",
        "next_validation": "Check whether Galaxy signs a tenant for Helios II's 830 MW and whether IREN's $4B ARR is "
                           "operational by February 2027; check SpaceX segment disclosures for external compute "
                           "rental revenue versus internal use.",
        "falsifier": "GPU rents fall back as short-term contracts roll off, leaving non-traditional owners with "
                     "under-used sites.",
        "thesis_sentence": "Powered compute is becoming a sellable product for owners outside the hyperscalers, making "
                           "power-ready sites and capacity financing key constraints.",
        "evidence_reviewed_at": EVIDENCE_UPDATED_AT,
        "analyst_scores": {"relevance": 4, "impact": 3},
        "match": {"anchors": ["gigawatt", "gigawatts", "megawatt", "megawatts", "data center", "data centers",
                              "data centre", "coreweave", "helios", "neocloud", "colocation"],
                  "context": ["power", "lease", "leased", "capacity", "compute", "gpu", "gpus", "ai", "financing",
                              "site", "campus", "spacex", "galaxy", "iren"],
                  "exclude": CRYPTO, "min_terms": 2, "topic": "powered compute capacity"},
        "discovery": {"label": "Milk Road, Nov 4, 2026", "url": "https://milkroad.com/ideas/why-our-team-keeps-buying-spacex/"},
        "evidence": [
            (SPCX, "primary", "supports",
             "Nameplate compute capacity of 1.7 GW at Sep 30, 2026 vs 0.6 GW at Sep 30, 2025; segments include "
             "Space, Connectivity and Super Intelligence."),
            (GLXY, "primary", "supports",
             "All 133 MW of Helios I, Phase I critical IT load delivered to CoreWeave under a lease; Q3 data-center "
             "adjusted EBITDA of $69M in the first full quarter of revenue-generating operations."),
            (GLXY, "primary", "challenges",
             "830 MW of approved capacity at Helios II is not yet under lease; Helios I, Phase II construction is "
             "funded by a $3.5B senior secured notes offering."),
            (IREN, "primary", "supports",
             "AI Cloud revenue $200M in the quarter ended Sep 30, 2026 vs $71M the prior quarter; contracted pricing "
             "+11% on 3-year and +12% on 5-year deals; after quarter-end, about $22M per IT-MW on a five-year "
             "contract with customer prepayment covering 90% of GPU capex."),
            (IREN, "primary", "challenges",
             "The more than $4B ARR target moved from year-end 2026 to January 2027 after a customer-requested change "
             "and supplier timing, and may extend to February 2027; per-MW revenue rests on internal assumptions."),
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
        "content_version": CONTENT_VERSION,
        "title": "Private 5G for critical infrastructure is real but early, and integrators may capture more value than radio vendors",
        "brief": ["Ericsson won the first stage of Queensland's rail private 5G network", "Ericsson Enterprise sales fell 10% (about +1% organically)", "Real deployments, but vendor revenue is not accelerating yet"],
        "dek": "Operators are testing cellular networks for operational systems; value may go to integrators and "
               "managed operators rather than radio vendors.",
        "takeaway": "Ericsson's Q3 report says it was selected for the first stage of Queensland's next-generation "
                    "rail communications network using mission-critical private 5G (a dedicated cellular network "
                    "built for safety-critical operations). The same report shows Enterprise segment sales down 10%, "
                    "about +1% organically. Operational adoption is real but early, and vendor revenue shows no "
                    "acceleration yet.",
        "caveats": [
            "One vendor and one contract, with no disclosed value.",
            "Flat organic segment revenue directly challenges near-term growth.",
        ],
        "sector": "Industrial connectivity",
        "themes": ["Private networks", "Critical infrastructure", "Managed services"],
        "direction": "Contested",
        "what_changed": "Ericsson's Q3 2026 report (6-K filed Oct 15, 2026) says it was selected for the first stage "
                        "of Queensland's next-generation rail communications network using mission-critical private 5G "
                        "capabilities. The same report shows Enterprise segment sales down 10% to SEK 4.6b — about +1% "
                        "organically after a divestment.",
        "changed_points": [
            "Ericsson Q3 report: selected for the first stage of Queensland's next-generation rail communications "
            "network with mission-critical private 5G.",
            "Same report: Enterprise segment sales −10% to SEK 4.6b; about +1% organically after the iconectiv "
            "divestment.",
        ],
        "why_now": "Rail and other critical-infrastructure operators are replacing legacy narrowband radio, and "
                   "mission-critical 5G features make cellular viable for operational systems, not just office "
                   "connectivity.",
        "market_indication": "Infrastructure contracts validate private 5G for operational use, but flat vendor "
                             "enterprise revenue suggests value goes to integration, devices and managed operations "
                             "rather than radio equipment.",
        "audiences": [
            {"segment": "Industrial operators", "role": "buyer",
             "who": "Rail, port, mining and utility operators replacing legacy radio.",
             "impact": "Cellular networks may replace narrowband radio for operational systems, changing capital and "
                       "operating costs.",
             "action": "Benchmark private 5G against current radio on uptime, coverage and total cost at one site.",
             "trigger": "Peers announce operational (not office) private 5G deployments with disclosed scope."},
            {"segment": "Service providers", "role": "benefits",
             "who": "Systems integrators and managed network operators.",
             "impact": "Operators rarely have in-house cellular skills, so integration and operations may capture "
                       "the value.",
             "action": "Package managed private-network operations for multi-site industrial clients.",
             "trigger": "Tenders specify managed operations alongside equipment."},
        ],
        "implications": [
            {"trend": "Mission-critical private 5G entering transport",
             "problem": "Operators cannot run cellular networks in-house",
             "buyer": "Rail, port and utility operators",
             "solution": "Managed private-network operations",
             "investigate": "Managed private-network operators and integrators (category)"},
            {"trend": "Connectivity upgrades need a business case",
             "problem": "The return on connectivity spending is hard to prove",
             "buyer": "Industrial operations and finance teams",
             "solution": "Measurement of downtime and safety-incident reduction",
             "investigate": "Industrial connectivity ROI-measurement tools (category)"},
        ],
        "card_implication": "Operators can pilot private 5G at one site and measure uptime and total cost.",
        "customer_validation": "Find Queensland procurement records for scope and value; ask 3–5 industrial operators "
                               "what would justify replacing their current radio.",
        "view_triggers": [
            "Competing vendors also report flat private-wireless revenue for two quarters.",
            "No new large operator deployments are announced.",
        ],
        "value_chain": ["RAN vendors", "Systems integrators", "Industrial devices", "Managed network services"],
        "confidence": "Low",
        "corroboration": "Single primary source",
        "confidence_rationale": "One vendor report with a contract selection but no disclosed value; flat organic "
                                "segment revenue directly challenges near-term acceleration.",
        "next_validation": "Find Queensland procurement records for scope and value; check other radio vendors' Q3 "
                           "enterprise and private-wireless figures for corroboration.",
        "falsifier": "Competing vendors also report flat private-wireless revenue over the next two quarters with no "
                     "new large operator deployments.",
        "thesis_sentence": "Mission-critical private 5G is being adopted for transport infrastructure, but flat vendor "
                           "revenue suggests value will go to integrators and managed operators.",
        "evidence_reviewed_at": VERIFIED_AT,
        "analyst_scores": {"relevance": 3, "impact": 3},
        "match": {"anchors": ["private 5g", "private network", "private networks", "private wireless",
                              "mission-critical", "ericsson", "nokia", "cbrs"],
                  "context": ["rail", "industrial", "network", "connectivity", "5g", "port", "ports", "mining",
                              "utility", "utilities", "enterprise"],
                  "exclude": CRYPTO, "min_terms": 2, "topic": "industrial and private networks"},
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

# Key figures: every value is copied verbatim from an evidence item above (no derived numbers).
FIGURES: dict[str, list[dict[str, Any]]] = {
    "gpu-rent-vs-token-deflation": [
        {"id": "ramp-token-price", "title": "Blended price businesses paid per million tokens (OpenAI + Anthropic)",
         "insight": "Down 26.8% in four weeks while token volume rose 37.1%.", "unit": "USD per million tokens",
         "source_url": RAMP, "source_label": "Ramp AI Index", "as_of": "2026-10-23",
         "bars": [{"label": "Week ending Sep 25, 2026", "value": 0.76}, {"label": "Week ending Oct 23, 2026", "value": 0.56}]},
    ],
    "enterprise-ai-spend-compounding": [
        {"id": "anthropic-100k-customers", "title": "Anthropic customers paying $100k+ a year (trailing twelve months)",
         "insight": "More than twelve times as many large customers in one year.", "unit": "customers",
         "source_url": S1, "source_label": "Anthropic, PBC S-1", "as_of": "2026-09-30",
         "bars": [{"label": "Sep 30, 2025", "value": 950, "note": "more than"},
                  {"label": "Sep 30, 2026", "value": 11900, "note": "more than"}]},
        {"id": "anthropic-h1-revenue", "title": "Anthropic revenue, six months ended June 30",
         "insight": "$1.2B to $16.3B year over year, alongside a $693M H1 2026 operating loss.", "unit": "USD billions",
         "source_url": S1, "source_label": "Anthropic, PBC S-1", "as_of": "2026-06-30",
         "bars": [{"label": "H1 2025", "value": 1.2}, {"label": "H1 2026", "value": 16.3}]},
    ],
    "memory-substrate-reallocation": [
        {"id": "intel-segments", "title": "Intel Q3 revenue by segment",
         "insight": "Data-center revenue rose 78% while PC-chip revenue fell about 5%.", "unit": "USD millions",
         "source_url": INTC, "source_label": "Intel Corp 10-Q (Q3 2026)", "as_of": "2026-09-26",
         "bars": [{"label": "Data center (DCAI) Q3 2025", "value": 4117}, {"label": "Data center (DCAI) Q3 2026", "value": 7318},
                  {"label": "PC chips (CCPG) Q3 2025", "value": 8535}, {"label": "PC chips (CCPG) Q3 2026", "value": 8097}]},
    ],
    "powered-compute-as-product": [
        {"id": "spacex-capacity", "title": "SpaceX nameplate compute capacity",
         "insight": "Nearly tripled in a year; installed capacity, not utilization.", "unit": "GW",
         "source_url": SPCX, "source_label": "Space Exploration Technologies 10-Q", "as_of": "2026-09-30",
         "bars": [{"label": "Sep 30, 2025", "value": 0.6}, {"label": "Sep 30, 2026", "value": 1.7}]},
    ],
}
for _sig in SIGNALS:
    if _sig["id"] in FIGURES:
        _sig["figures"] = FIGURES[_sig["id"]]
    _sig["content_version"] = CONTENT_VERSION

NOTE = {
    "headline": "AI costs, budgets and bottlenecks are shifting: six theses and the evidence behind them",
    "summary": "Each headline is the takeaway. Open one for the evidence, the counter-case and what to check next.",
    "takeaways": [
        "Output per GPU-hour, not list price, increasingly decides AI costs: older-GPU rents rose since August while "
        "blended token prices fell.",
        "Enterprise AI is a compounding budget line, and credit or outcome pricing will need trusted metering before "
        "buyers accept it.",
        "Memory, substrates and power-ready sites look like the binding constraints; in private 5G, integrators may "
        "capture more value than radio vendors.",
    ],
}

REQUIRED = ("title", "brief", "dek", "takeaway", "caveats", "sector", "themes", "direction", "what_changed", "why_now",
            "market_indication", "audiences", "implications", "card_implication", "customer_validation",
            "value_chain", "confidence", "corroboration", "confidence_rationale", "next_validation", "falsifier",
            "thesis_sentence", "evidence_reviewed_at", "evidence")
AUDIENCE_KEYS = ("segment", "role", "who", "impact", "action", "trigger")
IMPLICATION_KEYS = ("trend", "problem", "buyer", "solution", "investigate")


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
    for a in sig.get("audiences") or []:
        errs += [f"audience {a.get('segment')}: missing {k}" for k in AUDIENCE_KEYS if not a.get(k)]
        if a.get("role") not in ROLES:
            errs.append(f"audience {a.get('segment')}: role must be one of {ROLES}")
    segs = [a.get("segment") for a in sig.get("audiences") or []]
    if len(segs) != len(set(segs)):
        errs.append("duplicate audience segment")
    for f in sig.get("figures") or []:
        if f.get("source_url") not in DOCS or not f.get("bars") or not all(k in f for k in ("title", "unit", "as_of")):
            errs.append(f"figure {f.get('id')}: needs a registered source, title, unit, as_of and bars")
    for i in sig.get("implications") or []:
        errs += [f"implication missing {k}" for k in IMPLICATION_KEYS if not i.get(k)]
    brief = sig.get("brief") or []
    if len(brief) != 3 or any(len(b) > 80 for b in brief):
        errs.append("brief needs exactly three points of at most 80 characters")
    return errs


def _data(sig: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in sig.items() if k not in ("id", "evidence")}


def _doc_ids(conn: sqlite3.Connection) -> dict[str, int]:
    ids: dict[str, int] = {}
    for url, (src, title, stype, pub, event) in DOCS.items():
        row = conn.execute("SELECT id FROM documents WHERE canonical_url=?", (canonicalize(url),)).fetchone()
        if row:
            ids[url] = int(row["id"])
            continue
        item = RawItem(url=url, title=title, source_type=stype, published_at=pub, event_date=event,
                       meta={"verified_for_edition": EDITION_DATE})
        ids[url], _ = upsert_document(conn, item, src, VERIFIED_AT, origin="seed")
    return ids


def _write_evidence(conn: sqlite3.Connection, sig: dict[str, Any], doc_ids: dict[str, int]) -> None:
    conn.execute("DELETE FROM signal_evidence WHERE signal_id=?", (sig["id"],))
    for pos, (url, claim, stance, statement) in enumerate(sig["evidence"]):
        conn.execute("INSERT INTO signal_evidence(signal_id, document_id, claim_type, stance, statement, position) "
                     "VALUES (?,?,?,?,?,?)", (sig["id"], doc_ids[url], claim, stance, statement, pos))


def _upsert_note(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO edition_notes(edition_date, headline, summary, takeaways, created_at) VALUES (?,?,?,?,?) "
                 "ON CONFLICT(edition_date) DO UPDATE SET headline=excluded.headline, summary=excluded.summary, "
                 "takeaways=excluded.takeaways",
                 (EDITION_DATE, NOTE["headline"], NOTE["summary"], dumps(NOTE["takeaways"]), PUBLISHED_AT))


def _check() -> None:
    for sig in SIGNALS:
        errs = validate_signal(sig)
        if errs:
            raise ValueError(f"{sig['id']}: {errs}")


def seed_if_empty(conn: sqlite3.Connection) -> bool:
    """Seed an empty database; otherwise apply any newer editorial content (see sync_content)."""
    if conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]:
        sync_content(conn)
        return False
    seed(conn)
    return True


def seed(conn: sqlite3.Connection) -> None:
    _check()
    with tx(conn):
        for sid, name, kind, home, note in SOURCES:
            conn.execute("INSERT INTO sources(id, name, kind, homepage, access_note) VALUES (?,?,?,?,?) "
                         "ON CONFLICT(id) DO NOTHING", (sid, name, kind, home, note))
        doc_ids = _doc_ids(conn)
        for sig in SIGNALS:
            conn.execute("INSERT INTO signals(id, data, first_published_at, updated_at) VALUES (?,?,?,?)",
                         (sig["id"], dumps(_data(sig)), PUBLISHED_AT, REVISED_AT))
            conn.execute("INSERT INTO signal_revisions(signal_id, revised_at, reason, data) VALUES (?,?,?,?)",
                         (sig["id"], REVISED_AT, "first edition", dumps(_data(sig))))
            _write_evidence(conn, sig, doc_ids)
        _upsert_note(conn)
        run_id = int(conn.execute("INSERT INTO pipeline_runs(trigger, started_at, finished_at, status, summary) "
                                  "VALUES ('seed', ?, ?, 'seeded', ?)",
                                  (REVISED_AT, REVISED_AT, dumps({"note": "verified first edition loaded"}))
                                  ).lastrowid or 0)
        now = parse_iso(REVISED_AT)
        assert now is not None
        write_snapshot(conn, run_id, now, EDITION_DATE)


def sync_content(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """Apply editorial revisions to existing theses. Records a revision, keeps first-publication dates, re-checks
    unreviewed discovery matches under the current rules and writes a new snapshot for *today's* edition only;
    archived snapshots are never rewritten. Evidence review timestamps change only when a thesis's evidence was
    re-reviewed against its sources."""
    _check()
    now = now or utcnow()
    changed = 0
    with tx(conn):
        doc_ids = _doc_ids(conn)
        for sig in SIGNALS:
            data = _data(sig)
            row = conn.execute("SELECT data FROM signals WHERE id=?", (sig["id"],)).fetchone()
            if row and loads(row["data"]) == data:
                continue
            reviewed_before = loads(row["data"]).get("evidence_reviewed_at") if row else None
            evidence = "evidence re-reviewed" if reviewed_before != sig["evidence_reviewed_at"] else "evidence unchanged"
            reason = f"editorial revision v{CONTENT_VERSION}; {evidence}"
            if row:
                conn.execute("UPDATE signals SET data=?, updated_at=? WHERE id=?", (dumps(data), REVISED_AT, sig["id"]))
            else:
                conn.execute("INSERT INTO signals(id, data, first_published_at, updated_at) VALUES (?,?,?,?)",
                             (sig["id"], dumps(data), REVISED_AT, REVISED_AT))
            conn.execute("INSERT INTO signal_revisions(signal_id, revised_at, reason, data) VALUES (?,?,?,?)",
                         (sig["id"], REVISED_AT, reason, dumps(data)))
            _write_evidence(conn, sig, doc_ids)
            changed += 1
        if changed:
            _upsert_note(conn)
            rematch_ingested(conn, iso(now))
            run_id = int(conn.execute("INSERT INTO pipeline_runs(trigger, started_at, finished_at, status, summary) "
                                      "VALUES ('editorial', ?, ?, 'revised', ?)",
                                      (iso(now), iso(now), dumps({"revised_signals": changed}))).lastrowid or 0)
            write_snapshot(conn, run_id, now)
    return changed
