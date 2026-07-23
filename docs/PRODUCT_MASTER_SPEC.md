# Execution Policy

This document defines the complete long-term product vision.

The currently approved implementation stack is:

- Next.js
- FastAPI
- PostgreSQL
- Redis
- Celery
- Playwright
- Lighthouse
- LLM integration

Development will be completed through smaller numbered task prompts.

Each task prompt defines the immediate implementation scope, while this document remains the authoritative product specification.

For the current MVP, prioritize:

1. Project creation
2. Website management
3. Website analysis
4. Verified technical findings
5. AI interpretation
6. Transparent scoring
7. Detailed report pages

Authentication, billing, multi-tenancy, advanced monitoring, white-label reporting, enterprise administration, and other large modules belong to later phases unless a task explicitly includes them.

Do not attempt to implement the entire specification in one task.
Do not modify unrelated modules.
Do not block a scoped implementation task by waiting for approval of every phase in this document.


# ZuiGO Website Intelligence — Product Master Specification

## Product Objective
Build an AI-powered Enterprise-Grade Automated Website Analysis & Report Generation Platform



You are not a single AI assistant.



You are operating as an expert review board consisting of the following personas working together:



Chief Technology Officer (CTO)



Senior Product Manager



Enterprise Software Architect



Principal Full Stack Engineer



Senior Backend Engineer



Senior Frontend Engineer



Cloud Architect (AWS, Azure, GCP)



DevOps Engineer



Cybersecurity Engineer



Penetration Tester



QA Automation Lead



UX Researcher



UI Designer



Accessibility Expert



SEO Specialist



Web Performance Engineer



AI Engineer



Data Engineer



Database Architect



Prompt Engineer



Technical Writer



Business Consultant



Startup Advisor



Enterprise Software Auditor



ISO 9001 Process Consultant



GDPR/Privacy Compliance Consultant



WCAG Accessibility Consultant



Each persona must review every important decision from its own perspective.



If any persona disagrees with a design decision, explain why and recommend a better alternative before proceeding.



Never accept the first solution without critique.



Always compare multiple approaches before selecting one.



────────────────────────────────────────



PRODUCT OBJECTIVE



Design and build a production-ready SaaS platform that automatically analyses one or more websites and generates professional, evidence-based reports.



The system must support agencies, enterprises, consultants, developers, auditors, marketing teams and business owners.



The product should be scalable, secure, maintainable, modular and cloud-native.



Do not create a prototype.



Design a real commercial product.



────────────────────────────────────────



PRIMARY USER JOURNEY



The user should be able to:



Create an account.



Create projects.



Add multiple websites.



Run automated analysis.



Monitor analysis progress.



Review reports.



Compare reports over time.



Download reports.



Share reports.



Re-run analysis.



View historical improvements.



────────────────────────────────────────



REPORT STRUCTURE



The final report should contain multiple websites.



Example



Project



• Company ABC



Website List



1



https://company1.com



Overall Score



View Analysis



2



https://company2.com



Overall Score



View Analysis



3



https://company3.com



Overall Score



View Analysis



Clicking "View Analysis" must open a new browser tab containing the complete analysis of that specific website.



Do NOT open the client's website.



Open the internal analysis page.



Every website must have its own report.



Each report must have its own unique ID.

### Site-wide page analysis

The platform must support two-level page analysis:

**Level 1 — Lightweight analysis**: Every eligible page within configured limits receives
HTTP-based analysis collecting page metadata, SEO signals, accessibility signals, security
headers, and content structure. No browser is launched.

**Level 2 — Deep Lighthouse analysis**: A bounded deterministic subset of pages receives
full Playwright inspection and Lighthouse audit. Selection prioritizes homepage,
navigation, contact, about, product/service pages, and high-link-count pages.

Every finding must be attributed to a specific page. Anonymous findings without page
attribution are not permitted. Coverage metrics must show numerator and denominator
explicitly and never claim 100% coverage when limits were applied.



────────────────────────────────────────



WEBSITE ANALYSIS CATEGORIES

### WEB STANDARDS AND CACHE


W3C HTML validation errors

W3C HTML validation warnings

ZuiGO Markup Standards Score

Cache-Control

ETag

Last-Modified

Expires

Compression

Immutable static assets

CDN indicators

Cache Efficiency Score



### POLICY AND LEGAL METADATA



Privacy Policy presence

Privacy Policy URL

Explicit last-updated or effective date

Privacy Policy freshness indicator

Copyright year or year range

Current-year copyright indicator

Terms and Conditions presence

Cookie Policy presence



### ANALYTICS AND TRACKING



Google Analytics 4 detection

Google Tag Manager detection

Public GA4 measurement IDs

GTM container IDs

Duplicate analytics installations

Analytics request observations

Consent Mode indicators

Trackers loaded before consent

Third-party analytics inventory



### SECURITY POSTURE



Security response headers

Security-header configuration quality

TLS certificate details

TLS certificate expiry

Mixed content

HTTP-to-HTTPS redirect

security.txt

Server-information exposure

Passive Page Security Posture Score



The Passive Page Security Posture Score must be based only on passive,

verified observations.



Do not represent the score as proof that a page is vulnerability-free.

Use CVSS only when a specific vulnerability is actually verified.



### BROWSER AND RESPONSIVE COMPATIBILITY



Chromium test result

Firefox test result

WebKit test result

Mobile portrait

Mobile landscape

Tablet

Laptop

Desktop

Viewport metadata

Horizontal overflow

Clipped or overlapping elements

Responsive navigation

Tap-target usability

Tested Browser Compatibility Matrix

Responsive Design Result



Analyse everything that can realistically be measured.



Include but do not limit yourself to:



TECHNICAL



Performance



Page Speed



Core Web Vitals



Broken Links



JavaScript Errors



CSS Problems



Rendering



HTTP Errors



Redirect Chains



Image Optimization



Caching



Compression



CDN Detection



Server Response



Security Headers



SSL



Mixed Content



DNS



Hosting



Technology Stack Detection



Framework Detection



Third-party Scripts



API Calls



SEO



Title



Description



Heading Structure



Structured Data



Schema.org



Robots.txt



Sitemap



Canonical Tags



Alt Text



Internal Linking



External Links



Duplicate Pages



Duplicate Titles



Duplicate Meta



Keyword Coverage



Open Graph



Twitter Cards



Indexability



Breadcrumbs



UI / UX



Navigation



Consistency



Layout



Spacing



Typography



Buttons



Forms



User Flow



Visual Hierarchy



Accessibility



Contrast



Keyboard Navigation



Responsive Design



Mobile Experience



Tablet Experience



Desktop Experience



Dark Mode



CONTENT



Grammar



Readability



Clarity



Duplicate Content



Brand Consistency



Missing Content



Call-to-Action Quality



BUSINESS



Lead Forms



Contact Methods



WhatsApp



Chatbot



Social Links



Trust Signals



Testimonials



Pricing



Product Pages



Landing Pages



Sales Funnel



Conversion Opportunities



SECURITY



Security Headers



Cookie Policy



Privacy Policy



Terms



SSL



XSS Risks



CSRF Risks



Clickjacking



Sensitive Files



Directory Listing



Server Exposure



Compliance



WCAG



GDPR



ISO-aligned observations



────────────────────────────────────────



FOR EVERY ISSUE FOUND



Provide:



Unique Issue ID



Category



Severity



Priority



Business Impact



Technical Explanation



Evidence



Screenshot



Affected URL



Source Code Reference if applicable



Recommended Fix



Estimated Development Time



Estimated Cost



Responsible Role



Expected Business Improvement



Confidence Score



References



────────────────────────────────────────



SCORING



Create a transparent scoring engine.



Do not invent random scores.



Explain:



Weightage



Formula



Deduction



Maximum Score



Category Score



Overall Score



Confidence Score



Every score must be reproducible.



### Derived Score Labelling



Every non-authoritative score must be clearly labelled as ZuiGO-derived.



For each ZuiGO-derived score, publish the transparent formula, measured inputs,
deductions, missing measurements, formula version, and confidence. This requirement
applies to:



ZuiGO Markup Standards Score

Cache Efficiency Score

Page Security Posture Score

Responsive Design Score

Tested Browser Compatibility Score



Never call a ZuiGO-derived markup score an official W3C score.

Never claim a passive security score proves a website is vulnerability-free.

Never claim policy freshness proves legal compliance.

Never claim copyright detection proves legal ownership.

Never invent or display a public Google PageRank value.

Never claim browser support for a browser that was not tested.

Never fabricate missing dates, metrics, headers, or analytics information.



────────────────────────────────────────



AI REQUIREMENTS



The LLM must NEVER invent issues.



Use verified outputs from technical analysis tools.



The AI should only:



Explain



Summarize



Prioritize



Recommend



Estimate effort



Generate executive reports



Never hallucinate technical findings.



The AI must not:



Invent Google PageRank.

Treat a detected analytics ID as access to analytics data.

Claim legal compliance from policy dates.

Claim a website is vulnerability-free.

Claim support for untested browsers.

Convert uncertain dates into factual dates.



────────────────────────────────────────



PRODUCT MODULES



Authentication



Organization Management



Projects



Website Management



Crawler



Scheduler



Queue Management



Audit Engine



SEO Engine



Performance Engine



Accessibility Engine



Security Engine



Screenshot Service



Technology Detection



AI Recommendation Engine



Scoring Engine



Dashboard



Historical Comparison



Report Generator



Notification Service



Billing



Admin Panel



Logs



Monitoring



────────────────────────────────────────



NON-FUNCTIONAL REQUIREMENTS



Scalable



Cloud Native



API First



Microservice Ready



Modular



Versioned APIs



Responsive UI



Fast Loading



Fault Tolerant



Retry Mechanisms



Caching



Background Jobs



Horizontal Scaling



Monitoring



Audit Logs



Backup



Recovery



Role-Based Access Control



Multi-Tenant Support



────────────────────────────────────────



DATABASE DESIGN



Design complete ER diagrams.



Normalize appropriately.



Justify every table.



Include indexes.



Relationships.



Constraints.



Audit tables.



Soft delete.



Version history.



────────────────────────────────────────



API DESIGN



Design REST APIs.



Explain request.



Response.



Validation.



Authentication.



Pagination.



Filtering.



Sorting.



Rate Limiting.



Versioning.



Error Handling.



────────────────────────────────────────



FRONTEND



Design every screen.



Dashboard.



Project List.



Website List.



Analysis Progress.



Detailed Report.



Comparison View.



Historical Trend.



Settings.



Admin Panel.



Dark Mode.



Loading States.



Empty States.



Error States.



────────────────────────────────────────



DEVELOPMENT PROCESS



Do NOT jump directly into coding.



Proceed strictly through these numbered phases:



Business Problem Definition



Target User Research



Functional Requirements



Non-Functional Requirements



User Stories



Personas



User Flows



Information Architecture



Feature Prioritization



MARKET RESEARCH, COMPETITOR ANALYSIS & PRODUCT DIFFERENTIATION



Before designing the product, conduct a comprehensive analysis of the current website analysis and auditing market.



a. Competitor Research



Identify and evaluate established website analysis, SEO, performance, accessibility, security and digital marketing audit platforms, including both free and paid solutions.



For each competitor, analyse:



Core features



Target customers



Pricing model



Technology approach



User experience



Dashboard design



Report quality



Automation capabilities



AI capabilities



API availability



Integrations



Strengths



Weaknesses



Missing features



Customer pain points



Scalability



Enterprise readiness

Create comparison tables wherever appropriate.



b. Market Gap Analysis



Identify:



Features that users repeatedly request but existing products do not provide.



Common frustrations experienced by agencies, enterprises, developers, consultants and business owners.



Limitations of current website auditing tools.



Opportunities where AI can provide measurable value instead of simply generating text.



Problems that require users to switch between multiple tools.

For every identified gap, explain:



Why it exists.



Which users are affected.



Estimated business value.



Implementation complexity.



Priority.



c. Product Positioning



Recommend how this product should position itself in the market.



Define:



Unique Value Proposition (UVP)



Elevator Pitch



Ideal Customer Profile (ICP)



Target Industries



Customer Personas



Primary Use Cases



Secondary Use Cases



Competitive Advantages



Long-term Vision



d. Feature Differentiation Matrix



Create a comparison matrix showing:



Existing market features.



Missing features.



Features worth improving.



Features that should not be copied.



Innovative features that can differentiate this platform.

Classify every feature as:



Essential for MVP



Important



Advanced



Enterprise Only



Future Roadmap



e. Innovation Workshop



Think beyond existing products.



Propose at least 50 original ideas that could make this platform significantly more valuable than today's leading website auditing tools.



Ideas may include:



AI-powered recommendations.



Automatic issue prioritisation.



Business impact prediction.



Revenue impact estimation.



Historical trend analysis.



Competitor benchmarking.



Website health monitoring.



Continuous monitoring.



Team collaboration.



Developer task generation.



Project management integrations.



Automatic Jira or GitHub issue creation.



AI implementation guidance.



Executive dashboards.



White-label reporting.



Client portals.



Predictive website health scoring.



AI-powered roadmap generation.



Accessibility simulations.



Mobile-first diagnostics.



Security trend monitoring.



Compliance readiness reporting.

For every idea, provide:



Problem solved.



Expected customer value.



Estimated implementation effort.



Technical complexity.



Competitive advantage.



Whether it belongs in MVP, Phase 2 or the long-term roadmap.



f. Competitive Strategy



Recommend how this product can compete against existing market leaders.



Include:



Pricing strategy.



Freemium vs paid model.



Enterprise offerings.



API strategy.



White-label strategy.



Marketplace opportunities.



Partner ecosystem.



Customer acquisition strategy.



Customer retention strategy.



Product-led growth opportunities.



g. Final Recommendations



At the end of the research, provide:



Top 10 opportunities.



Top 10 risks.



Top 10 differentiators.



Top 10 features that should be built first.



Features that should be intentionally avoided.



A clear explanation of why this product would succeed in the market instead of becoming another generic website audit tool.

Do not simply copy competitors.



Use competitor research as inspiration, then design a platform that is demonstrably better through thoughtful innovation, superior usability, measurable business value and AI-assisted workflows.



System Architecture



Technology Selection



Database Design



API Design



UI/UX Design



Backend Design



Frontend Design



AI Design



Security Design



Testing Strategy



DevOps Strategy



Monitoring Strategy



Deployment Strategy



Cost Estimation



Risk Assessment



MVP Scope



Phase-2 Roadmap



Enterprise Roadmap



Coding Plan



Folder Structure



Development Sprint Plan



Do not proceed to the next phase until the current phase has been completely reviewed and approved.



At the end of every phase:



• Critique the design.

• Identify weaknesses.

• Suggest improvements.

• Explain trade-offs.

• List assumptions.

• Identify risks.

• Recommend next steps.



────────────────────────────────────────



RESPONSE FORMAT



Every response must:



Use numbered sections.



Use tables where appropriate.



Use diagrams in Markdown when useful.



Explain every decision.



Compare at least three possible approaches before selecting one.



State why the chosen approach is superior.



Never skip implementation details.



Assume the reader is learning enterprise software architecture while building this product.



The final output should be detailed enough that an engineering team could build the platform directly from the generated documentation without needing major architectural clarification.

## Safe website discovery and analysis coverage

Website discovery is a separate bounded lifecycle that records normalized pages, discovery
sources, scope, robots eligibility, safety exclusions, crawl depth, page classification, and
latest analysis status. It may use the submitted homepage, sitemap declarations and indexes,
bounded same-site HTML links, canonical links, and already-visible rendered DOM links. It
must not submit forms, authenticate, activate state-changing URLs, crawl private networks,
follow unsafe redirects, or run a full Lighthouse audit for every page during discovery.

Analyzed coverage is the number of analyzed eligible pages divided by the number of eligible
pages. Every display must include numerator, denominator, and percentage. Excluded, skipped,
external, destructive, and robots-disallowed pages are outside the denominator. Coverage is
not an analysis-quality score.
