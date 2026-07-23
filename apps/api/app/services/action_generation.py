# ruff: noqa: E501
"""Action Generation Service.

Converts page-analysis findings and recommendations into persistent,
grouped, prioritized action items with full status tracking.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_plan import (
    ActionGenerationExecution,
    ActionGroup,
    ActionItem,
    ActionStatusHistory,
)
from app.models.analysis_finding import AnalysisFinding
from app.models.page_analysis_run import PageAnalysisRun
from app.services.priority import calculate_priority_score

PAGE_ANALYSIS_SOURCE = "page_analysis"

FINDING_TO_ACTION_MAP: dict[str, dict[str, Any]] = {
    "MISSING_PAGE_TITLE": {
        "issue_title": "Missing page title",
        "category": "seo",
        "severity": "high",
        "grouping_key": "missing_page_title",
        "estimated_effort": "low",
        "business_impact": "moderate",
        "responsible_area": "CMS/content",
        "responsible_role": "Content editor",
        "action_location": "Page metadata",
        "why_this_matters": "Page titles are the first thing users see in search results and browser tabs. Without a title, search engines cannot display a meaningful result, which reduces click-through rates and harms SEO rankings.",
        "exact_correction": "Add a descriptive <title> element inside the HTML <head> that accurately describes each page's content.",
        "implementation_steps": "1. Open the page template or CMS page editor.\n2. Locate the <title> element in the HTML head.\n3. Add a unique, descriptive title (50-60 characters) including primary keywords.\n4. Repeat for every page or ensure the template dynamically generates page-specific titles.",
        "verification_steps": "1. Visit the page and view the HTML source.\n2. Check that the <title> element is present and contains meaningful text.\n3. Verify the title displays correctly in the browser tab.",
        "expected_result": "Every page will have a visible, search-engine-friendly title in browser tabs and SERP snippets.",
        "limitations": "This check verifies title element presence only. Title quality, length, and keyword optimization require manual review.",
        "score_impact": 15,
    },
    "MISSING_META_DESCRIPTION": {
        "issue_title": "Missing meta description",
        "category": "seo",
        "severity": "medium",
        "grouping_key": "missing_meta_description",
        "estimated_effort": "low",
        "business_impact": "moderate",
        "responsible_area": "CMS/content",
        "responsible_role": "Content editor",
        "action_location": "Page metadata",
        "why_this_matters": "Meta descriptions appear below the title in search results and influence whether users click through. Pages without descriptions appear less relevant and may receive fewer clicks.",
        "exact_correction": "Add a meta description element in the HTML <head> that summarizes the page content in 150-160 characters.",
        "implementation_steps": '1. Open the page template or CMS SEO settings.\n2. Add <meta name="description" content="..." /> to the HTML head.\n3. Write a unique summary for each page including target keywords naturally.\n4. Preview how it appears in search result snippets.',
        "verification_steps": "1. View the page HTML source.\n2. Look for the meta description element.\n3. Check that the content is non-empty and relevant to the page.",
        "expected_result": "Search results will display descriptive snippets, potentially improving click-through rates.",
        "limitations": "Search engines may choose to display different text. This check only confirms the element exists and is non-empty.",
        "score_impact": 10,
    },
    "MISSING_CANONICAL_URL": {
        "issue_title": "Missing canonical URL",
        "category": "seo",
        "severity": "medium",
        "grouping_key": "missing_canonical_url",
        "estimated_effort": "low",
        "business_impact": "moderate",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Page head template",
        "why_this_matters": "Canonical URLs tell search engines which version of a page is the authoritative one. Without them, duplicate content can dilute ranking signals and cause indexing issues.",
        "exact_correction": 'Add a rel="canonical" link element pointing to the page\'s preferred URL.',
        "implementation_steps": '1. Open the shared page head template.\n2. Add <link rel="canonical" href="..." /> dynamically populated with each page\'s canonical URL.\n3. Verify the href matches the preferred URL (usually the HTTPS, non-www version).',
        "verification_steps": "1. View the HTML source of multiple pages.\n2. Confirm each page has a self-referencing or correct canonical link.\n3. Check there are no conflicting canonical declarations.",
        "expected_result": "Search engines receive clear signals about the preferred page URL, reducing duplicate-content risks.",
        "limitations": "This check only detects the presence of a canonical link element, not its correctness.",
        "score_impact": 8,
    },
    "MISSING_H1": {
        "issue_title": "Missing H1 heading",
        "category": "seo",
        "severity": "medium",
        "grouping_key": "missing_h1",
        "estimated_effort": "low",
        "business_impact": "moderate",
        "responsible_area": "CMS/content",
        "responsible_role": "Content editor",
        "action_location": "Page content template",
        "why_this_matters": "H1 headings are a primary signal to search engines about page topic and hierarchy. Missing H1s reduce SEO clarity and accessibility for screen reader users.",
        "exact_correction": "Add exactly one H1 heading that clearly describes the page's main topic.",
        "implementation_steps": "1. Open the page content or CMS editor.\n2. Ensure there is exactly one <h1> element on the page.\n3. Write the H1 to be descriptive and include primary keywords.",
        "verification_steps": "1. Check the page for the presence of exactly one <h1> element.\n2. Confirm it appears near the top of the visible content.",
        "expected_result": "Each page will have a clear, hierarchical heading structure starting with a single H1.",
        "limitations": "This check confirms presence and count only. Heading quality requires manual review.",
        "score_impact": 8,
    },
    "MULTIPLE_H1": {
        "issue_title": "Multiple H1 headings",
        "category": "seo",
        "severity": "low",
        "grouping_key": "multiple_h1",
        "estimated_effort": "low",
        "business_impact": "minor",
        "responsible_area": "CMS/content",
        "responsible_role": "Content editor",
        "action_location": "Page content template",
        "why_this_matters": "Multiple H1 headings confuse the page hierarchy and can dilute topical relevance signals for search engines.",
        "exact_correction": "Use only one H1 per page and restructure additional major headings as H2 elements.",
        "implementation_steps": "1. Identify all H1 elements on the page.\n2. Keep the most important one as H1.\n3. Change the others to H2 or lower headings as appropriate.",
        "verification_steps": "1. Inspect the page heading structure.\n2. Count H1 elements — confirm exactly one exists.",
        "expected_result": "Pages will have a clean, single-root heading hierarchy.",
        "limitations": "This check counts H1 elements only. The semantic correctness of the heading structure requires manual review.",
        "score_impact": 3,
    },
    "IMAGES_MISSING_ALT": {
        "issue_title": "Images missing alternative text",
        "category": "accessibility",
        "severity": "medium",
        "grouping_key": "images_missing_alt",
        "estimated_effort": "low",
        "business_impact": "moderate",
        "responsible_area": "CMS/content",
        "responsible_role": "Content editor",
        "action_location": "Image component",
        "why_this_matters": "Alternative text is essential for screen reader users and is displayed when images fail to load. Missing alt text makes images inaccessible and harms SEO.",
        "exact_correction": 'Add descriptive alt attributes to all images that convey meaning. Decorative images should use alt="" (empty).',
        "implementation_steps": '1. Review all images on each affected page.\n2. For each informative image, add alt text describing its content and function.\n3. For decorative images, set alt="" (empty) so screen readers skip them.\n4. Ensure the CMS or template enforces alt text requirements.',
        "verification_steps": "1. Use an accessibility checker or inspect each <img> element.\n2. Confirm every image has an alt attribute.\n3. Ensure decorative images use empty alt text, not missing or placeholder text.",
        "expected_result": "All images will be accessible to screen readers and search engine crawlers will index image content properly.",
        "limitations": "This check confirms alt attribute presence. Alt text quality, accuracy, and appropriateness require manual review.",
        "score_impact": 8,
    },
    "MISSING_HTML_LANGUAGE": {
        "issue_title": "Missing HTML language attribute",
        "category": "accessibility",
        "severity": "medium",
        "grouping_key": "missing_html_language",
        "estimated_effort": "low",
        "business_impact": "minor",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Root HTML element",
        "why_this_matters": "The lang attribute on the <html> element tells browsers and screen readers the page's language. Without it, assistive technologies may mispronounce or fail to render content.",
        "exact_correction": "Add the lang attribute to the <html> element with the appropriate language code.",
        "implementation_steps": '1. Open the root layout or HTML template.\n2. Change <html> to <html lang="en"> (or the appropriate language code).\n3. Use dynamic language detection if the site supports multiple languages.',
        "verification_steps": "1. Inspect the <html> tag in the rendered page source.\n2. Confirm the lang attribute is present and contains a valid language code.",
        "expected_result": "Browsers and assistive technologies will correctly interpret the page language.",
        "limitations": "This check confirms attribute presence only. Language code correctness and regional subtags require manual review.",
        "score_impact": 5,
    },
    "NON_HTTPS_WEBSITE": {
        "issue_title": "Website not using HTTPS",
        "category": "security",
        "severity": "high",
        "grouping_key": "non_https",
        "estimated_effort": "medium",
        "business_impact": "critical",
        "responsible_area": "CDN/server",
        "responsible_role": "DevOps",
        "action_location": "Web server configuration",
        "why_this_matters": "HTTPS encrypts data between the browser and server, protecting users from eavesdropping and man-in-the-middle attacks. Search engines also rank HTTPS sites higher, and browsers mark HTTP sites as 'Not Secure'.",
        "exact_correction": "Configure HTTPS with a valid TLS certificate and redirect all HTTP traffic to HTTPS.",
        "implementation_steps": "1. Obtain a TLS certificate (e.g., via Let's Encrypt, cloud provider, or CDN).\n2. Configure the web server or reverse proxy to use the certificate.\n3. Set up a 301 redirect from http:// to https:// for all URLs.\n4. Add HSTS header: Strict-Transport-Security: max-age=31536000; includeSubDomains.\n5. Update all internal links to use https:// URLs.",
        "verification_steps": "1. Visit the site with https:// and check the browser padlock icon.\n2. Use curl -vI https://example.com to verify TLS handshake and certificate.\n3. Confirm HTTP requests redirect to HTTPS with a 301 status code.\n4. Test for mixed content warnings using browser DevTools.",
        "expected_result": "All traffic will be encrypted. Users will see a secure padlock and search engines will not penalise the site for lacking HTTPS.",
        "limitations": "This check detects HTTPS availability at the server level. It does not verify certificate authority trust, key strength, or internal mixed-content issues uncovered during browsing.",
        "score_impact": 30,
    },
    "MISSING_X_FRAME_OPTIONS": {
        "issue_title": "Missing X-Frame-Options header",
        "category": "security",
        "severity": "medium",
        "grouping_key": "missing_x_frame_options",
        "estimated_effort": "low",
        "business_impact": "moderate",
        "responsible_area": "CDN/server",
        "responsible_role": "DevOps",
        "action_location": "HTTP response headers",
        "why_this_matters": "The X-Frame-Options header prevents clickjacking attacks by controlling whether the page can be embedded in frames or iframes on other sites.",
        "exact_correction": "Add X-Frame-Options: DENY or X-Frame-Options: SAMEORIGIN to the HTTP response headers.",
        "implementation_steps": '1. Access the web server or reverse proxy configuration.\n2. Add: add_header X-Frame-Options "SAMEORIGIN"; (for nginx) or Header always set X-Frame-Options "SAMEORIGIN" (for Apache).\n3. If using a CDN or WAF, add the header in the security rules.\n4. Restart or reload the web server.',
        "verification_steps": "1. Check response headers using curl -vI https://example.com or browser DevTools.\n2. Confirm X-Frame-Options is present with a secure value.",
        "expected_result": "The site will be protected against basic clickjacking attacks by preventing framing from unauthorised origins.",
        "limitations": "X-Frame-Options is a legacy header superseded by CSP frame-ancestors. CSP provides more granular control and should be used alongside or instead of this header.",
        "score_impact": 8,
    },
    "MISSING_X_CONTENT_TYPE_OPTIONS": {
        "issue_title": "Missing X-Content-Type-Options header",
        "category": "security",
        "severity": "medium",
        "grouping_key": "missing_x_content_type_options",
        "estimated_effort": "low",
        "business_impact": "moderate",
        "responsible_area": "CDN/server",
        "responsible_role": "DevOps",
        "action_location": "HTTP response headers",
        "why_this_matters": "The X-Content-Type-Options: nosniff header prevents browsers from MIME-type sniffing, which can otherwise be exploited to execute malicious content disguised as a different file type.",
        "exact_correction": "Add X-Content-Type-Options: nosniff to the HTTP response headers.",
        "implementation_steps": '1. Access the web server or reverse proxy configuration.\n2. Add: add_header X-Content-Type-Options "nosniff"; (for nginx) or Header always set X-Content-Type-Options "nosniff" (for Apache).\n3. Restart or reload the web server.',
        "verification_steps": "1. Check response headers using curl -vI https://example.com or browser DevTools.\n2. Confirm X-Content-Type-Options: nosniff is present.",
        "expected_result": "Browsers will respect declared Content-Type headers and refuse to sniff responses, reducing drive-by download risks.",
        "limitations": "This header only protects against MIME sniffing in modern browsers. Content security requires additional headers and practices.",
        "score_impact": 5,
    },
    "CSS_MIME_TYPE_FAILURE": {
        "issue_title": "MIME type validation failure for stylesheets",
        "category": "technical",
        "severity": "high",
        "grouping_key": "css_mime_type_failure",
        "estimated_effort": "medium",
        "business_impact": "moderate",
        "responsible_area": "CDN/server",
        "responsible_role": "DevOps",
        "action_location": "Web server or CDN configuration",
        "why_this_matters": "Chromium rejects stylesheets served with incorrect MIME types, causing layout and visual rendering failures. Visitors may see unstyled or partially styled pages.",
        "exact_correction": "Ensure CSS files are served with Content-Type: text/css. Configure the web server or CDN to send the correct MIME type for .css files.",
        "implementation_steps": "1. Identify affected stylesheet URLs from the evidence.\n2. Check the server configuration for MIME type mappings.\n3. Add or correct the mapping for .css files: text/css.\n4. If using a CDN, verify the CDN's MIME type configuration.\n5. Clear any CDN or server caches and verify with curl.",
        "verification_steps": "1. Run curl -vI https://example.com/path/to/style.css and check Content-Type header.\n2. Verify the value is exactly text/css.\n3. Load the page in a browser and confirm styles are applied correctly.",
        "expected_result": "All stylesheets will load correctly, ensuring proper page rendering.",
        "limitations": "This check identifies stylesheets blocked by MIME type mismatch. Additional stylesheet errors may exist beyond the sample.",
        "score_impact": 15,
    },
    "FIRST_PARTY_JAVASCRIPT_FAILURE": {
        "issue_title": "First-party JavaScript failed to load",
        "category": "technical",
        "severity": "critical",
        "grouping_key": "first_party_js_failure",
        "estimated_effort": "high",
        "business_impact": "critical",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Page script references",
        "why_this_matters": "First-party JavaScript files that fail to load can break critical page functionality, interactive elements, and user flows.",
        "exact_correction": "Investigate and fix the failing script URLs. Check file paths, server configuration, and file availability.",
        "implementation_steps": "1. Review the failed script URLs from the evidence.\n2. Check if files exist at the referenced paths.\n3. Verify file permissions and server routing.\n4. Check for typos or incorrect paths in script tags.\n5. Test after correcting the issues.",
        "verification_steps": "1. Load the page in a browser with DevTools open (Network tab).\n2. Confirm the previously failing scripts now load with HTTP 200 status.\n3. Verify that dependent page functionality works correctly.",
        "expected_result": "Critical page scripts will load and execute, restoring full page functionality.",
        "limitations": "This check identifies loading failures only. Runtime JavaScript errors are reported separately.",
        "score_impact": 35,
    },
    "FAILED_NETWORK_REQUESTS": {
        "issue_title": "Failed network requests detected",
        "category": "technical",
        "severity": "medium",
        "grouping_key": "failed_network_requests",
        "estimated_effort": "medium",
        "business_impact": "moderate",
        "responsible_area": "backend",
        "responsible_role": "Developer",
        "action_location": "Page URL or server configuration",
        "why_this_matters": "Failed network requests for resources like fonts, scripts, or API calls can degrade page functionality and user experience. Some failures may indicate configuration issues or broken dependencies.",
        "exact_correction": "Investigate each failed request and resolve the underlying cause (missing file, server error, incorrect URL).",
        "implementation_steps": "1. Review the list of failed requests from the evidence.\n2. Categorise by failure type (404, 500, CORS, timeout, etc.).\n3. Fix missing or broken resource references.\n4. Address server errors for dynamic endpoints.\n5. Configure proper error handling for third-party resource failures.",
        "verification_steps": "1. Reload the page and check the Network tab.\n2. Confirm all expected resources load successfully.\n3. Verify the page functions correctly without console errors.",
        "expected_result": "All page resources will load successfully, eliminating broken dependencies and improving reliability.",
        "limitations": "This check captures a snapshot of requests. Not all failed requests may be reproducible in every session.",
        "score_impact": 8,
    },
    "POOR_LIGHTHOUSE_PERFORMANCE": {
        "issue_title": "Poor Lighthouse performance score",
        "category": "performance",
        "severity": "medium",
        "grouping_key": "poor_performance",
        "estimated_effort": "high",
        "business_impact": "major",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Frontend performance optimisation",
        "why_this_matters": "Low performance scores indicate slow page loads, which frustrate users, increase bounce rates, and harm search engine rankings. Core Web Vitals are now a direct ranking factor.",
        "exact_correction": "Implement performance improvements targeting the specific Lighthouse audit failures identified in the report.",
        "implementation_steps": "1. Review the full Lighthouse report for specific failing audits.\n2. Prioritise: LCP improvement (above-the-fold content, image optimisation, CDN).\n3. Reduce JavaScript bundle sizes (code splitting, tree shaking).\n4. Optimise images (WebP, responsive sizes, lazy loading).\n5. Minimise render-blocking resources. Defer non-critical CSS/JS.\n6. Implement caching strategies and CDN delivery.",
        "verification_steps": "1. Re-run Lighthouse analysis after changes.\n2. Compare before/after scores.\n3. Verify real-user metrics are improving using analytics or RUM data.",
        "expected_result": "Improved page load speeds, better Core Web Vitals, higher Lighthouse scores, and improved user experience.",
        "limitations": "Lighthouse is a lab-based tool. Lab scores do not always match real-user experience. Field data from CrUX or RUM provides complementary insight.",
        "score_impact": 12,
    },
    "POOR_LIGHTHOUSE_ACCESSIBILITY": {
        "issue_title": "Poor Lighthouse accessibility score",
        "category": "accessibility",
        "severity": "medium",
        "grouping_key": "poor_accessibility",
        "estimated_effort": "high",
        "business_impact": "major",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Frontend accessibility improvements",
        "why_this_matters": "Low accessibility scores mean the site is difficult or impossible to use for people with disabilities. This can exclude users and expose the business to legal risk under accessibility regulations.",
        "exact_correction": "Address the specific accessibility audit failures identified by Lighthouse.",
        "implementation_steps": "1. Review the full Lighthouse accessibility audit for specific failures.\n2. Fix colour contrast issues.\n3. Add proper ARIA attributes where needed.\n4. Ensure keyboard navigation works throughout the site.\n5. Add focus indicators and skip navigation links.\n6. Fix heading hierarchy and form label associations.",
        "verification_steps": "1. Re-run Lighthouse accessibility audit.\n2. Test with keyboard navigation only.\n3. Test with a screen reader (NVDA, VoiceOver, or JAWS).\n4. Consider manual WCAG audit for complete compliance verification.",
        "expected_result": "Improved accessibility, better experience for users with disabilities, and reduced legal compliance risk.",
        "limitations": "Automated accessibility checks (including Lighthouse) only catch approximately 30-40% of WCAG issues. Manual testing and user testing with assistive technologies are essential for complete coverage.",
        "score_impact": 10,
    },
    "POOR_LIGHTHOUSE_SEO": {
        "issue_title": "Poor Lighthouse SEO score",
        "category": "seo",
        "severity": "medium",
        "grouping_key": "poor_seo",
        "estimated_effort": "medium",
        "business_impact": "major",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Frontend SEO improvements",
        "why_this_matters": "Low SEO scores indicate search engines may struggle to index and rank the site properly. This directly affects organic traffic and visibility.",
        "exact_correction": "Address the specific SEO audit failures identified by Lighthouse.",
        "implementation_steps": "1. Review the full Lighthouse SEO audit for specific failures.\n2. Ensure pages are crawlable and indexable.\n3. Add or fix meta tags, structured data, and heading structure.\n4. Fix any crawl issues like broken links or incorrect robots directives.\n5. Ensure proper use of canonical tags and hreflang where applicable.",
        "verification_steps": "1. Re-run Lighthouse SEO audit.\n2. Use Google Search Console to check for indexing issues.\n3. Test with a crawler or SEO tool to verify improvements.",
        "expected_result": "Improved search engine indexing and potential ranking improvements.",
        "limitations": "Lighthouse SEO checks are basic. Comprehensive SEO requires analysis of content quality, backlinks, keyword targeting, and competitor positioning.",
        "score_impact": 10,
    },
    "POOR_LIGHTHOUSE_BEST_PRACTICES": {
        "issue_title": "Poor Lighthouse best-practices score",
        "category": "technical",
        "severity": "medium",
        "grouping_key": "poor_best_practices",
        "estimated_effort": "medium",
        "business_impact": "moderate",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Frontend code quality",
        "why_this_matters": "Low best-practices scores indicate potentially unsafe or outdated web development practices, including deprecated APIs, known security issues, or non-standard implementations.",
        "exact_correction": "Address the specific best-practices audit failures identified by Lighthouse.",
        "implementation_steps": "1. Review the specific failing best-practices audits.\n2. Fix deprecated API usages.\n3. Address any detected security issues (e.g., insecure libraries).\n4. Update outdated dependencies.\n5. Ensure proper error logging without exposing sensitive information.",
        "verification_steps": "1. Re-run Lighthouse best-practices audit.\n2. Verify all previously failing checks now pass.",
        "expected_result": "Improved code quality and adherence to modern web development best practices.",
        "limitations": "Lighthouse best-practices checks cover a limited set of common issues. A comprehensive code audit requires additional tooling.",
        "score_impact": 6,
    },
    "HIGH_LCP": {
        "issue_title": "High Largest Contentful Paint (LCP)",
        "category": "performance",
        "severity": "high",
        "grouping_key": "high_lcp",
        "estimated_effort": "high",
        "business_impact": "major",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Frontend performance optimisation",
        "why_this_matters": "LCP measures perceived load speed. High LCP means users wait longer to see the main content, increasing bounce rates and negatively affecting Core Web Vitals rankings.",
        "exact_correction": "Optimise the largest contentful element's loading path: optimise images, reduce server response time, eliminate render-blocking resources, and use CDN delivery.",
        "implementation_steps": "1. Identify the LCP element (reported in evidence).\n2. If an image: optimise (compress, WebP, responsive sizes), lazy load below-fold images, preload above-fold critical image.\n3. If text: preload the font, reduce CLS.\n4. Reduce server response time (TTFB).\n5. Eliminate render-blocking resources.\n6. Use a CDN for static assets.",
        "verification_steps": "1. Re-run Lighthouse performance audit.\n2. Compare LCP before vs after.\n3. Monitor real-user LCP via CrUX or RUM.",
        "expected_result": "Faster perceived load time, improved Core Web Vitals, better user experience and SEO.",
        "limitations": "LCP measured in Lighthouse is a lab value. Real-user LCP varies by device, network, and location.",
        "score_impact": 20,
    },
    "HIGH_CLS": {
        "issue_title": "High Cumulative Layout Shift (CLS)",
        "category": "performance",
        "severity": "medium",
        "grouping_key": "high_cls",
        "estimated_effort": "medium",
        "business_impact": "moderate",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Frontend rendering optimisation",
        "why_this_matters": "High CLS causes visible page layout shifts that frustrate users, especially when they are about to click or read something. This harms user experience and is a Core Web Vital metric.",
        "exact_correction": "Fix layout shifts by setting explicit dimensions for images, ads, embeds, and dynamically injected content.",
        "implementation_steps": "1. Identify elements causing layout shifts (review evidence).\n2. Add explicit width and height attributes to all images and videos.\n3. Reserve space for dynamic content (ads, embeds, banners) using CSS aspect ratio boxes or min-height.\n4. Avoid injecting content above existing content after the page has loaded.\n5. Use font-display: swap to prevent invisible text layout shifts.",
        "verification_steps": "1. Re-run Lighthouse performance audit.\n2. Compare CLS before vs after.\n3. Resize browser window and test on mobile viewports.",
        "expected_result": "Stable page layout during load, no unexpected shifts, improved user experience.",
        "limitations": "Some CLS sources (third-party embeds, A/B testing tools) are difficult to control fully.",
        "score_impact": 8,
    },
    "HIGH_TOTAL_BLOCKING_TIME": {
        "issue_title": "High Total Blocking Time (TBT)",
        "category": "performance",
        "severity": "high",
        "grouping_key": "high_tbt",
        "estimated_effort": "high",
        "business_impact": "major",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Frontend JavaScript optimisation",
        "why_this_matters": "High TBT means the main thread is blocked by long JavaScript tasks, making the page feel sluggish and unresponsive. This directly impacts interactivity metrics and user experience.",
        "exact_correction": "Reduce main-thread work by breaking up long tasks, deferring non-critical JavaScript, and optimising heavy computations.",
        "implementation_steps": "1. Identify long tasks from the evidence.\n2. Break up long JavaScript tasks using techniques like code splitting, web workers, or idle callbacks.\n3. Defer non-critical JavaScript with async/defer attributes.\n4. Optimise heavy libraries or replace with lighter alternatives.\n5. Implement lazy loading for below-fold interactive elements.",
        "verification_steps": "1. Re-run Lighthouse performance audit.\n2. Compare TBT before vs after.\n3. Test interactivity manually on a throttled connection.",
        "expected_result": "Improved page interactivity, lower TBT, better Core Web Vitals, and a more responsive user experience.",
        "limitations": "TBT is a lab metric approximating First Input Delay (FID). Real-user interactivity may differ.",
        "score_impact": 18,
    },
    "JAVASCRIPT_RUNTIME_ERRORS": {
        "issue_title": "JavaScript runtime errors detected",
        "category": "technical",
        "severity": "high",
        "grouping_key": "js_runtime_errors",
        "estimated_effort": "medium",
        "business_impact": "moderate",
        "responsible_area": "frontend",
        "responsible_role": "Developer",
        "action_location": "Page JavaScript implementation",
        "why_this_matters": "JavaScript runtime errors can break page functionality, prevent interactive elements from working, and cause poor user experiences. Unhandled errors may also indicate deeper code quality issues.",
        "exact_correction": "Investigate each JavaScript error, fix the root cause, and implement proper error handling.",
        "implementation_steps": "1. Review the JavaScript error messages from the evidence.\n2. Reproduce each error in a browser console.\n3. Fix the root cause (null reference, undefined variable, incorrect API call, etc.).\n4. Add try/catch blocks for unhandled promise rejections.\n5. Implement global error handling with window.onerror and unhandledrejection.",
        "verification_steps": "1. Load the page and check browser console.\n2. Confirm previously reported errors no longer appear.\n3. Test all interactive features on the page.",
        "expected_result": "Clean browser console without JavaScript errors, improved page stability and functionality.",
        "limitations": "This check captures errors from a single page load. Some errors may depend on specific user interactions.",
        "score_impact": 20,
    },
}

FAILURE_REASON_ACTION_MAP: dict[str, dict[str, Any]] = {
    "unsupported_content_type": {
        "issue_title": "Page has unsupported content type",
        "category": "technical",
        "severity": "low",
        "grouping_key": "unsupported_content_type",
        "estimated_effort": "low",
        "business_impact": "minor",
        "responsible_area": "backend",
        "responsible_role": "Developer",
        "action_location": "Page URL or content delivery",
        "why_this_matters": "Pages with unsupported content types are not analysed. If the URL should return HTML, the content type configuration needs correction.",
        "exact_correction": "Ensure the URL returns HTML content with Content-Type: text/html.",
        "implementation_steps": "1. Check the URL returns proper Content-Type header.\n2. If dynamic routing: fix the content negotiation logic.\n3. If static files: ensure .html extension and correct MIME mapping.",
        "verification_steps": "1. Check Content-Type response header with curl.\n2. Verify it returns text/html.",
        "expected_result": "The URL will return HTML content that can be properly analysed.",
        "limitations": "Some URLs intentionally return non-HTML content (API endpoints, file downloads), which is expected behavior.",
        "score_impact": 2,
    },
    "timeout": {
        "issue_title": "Page analysis timed out",
        "category": "technical",
        "severity": "medium",
        "grouping_key": "timeout",
        "estimated_effort": "medium",
        "business_impact": "moderate",
        "responsible_area": "CDN/server",
        "responsible_role": "DevOps",
        "action_location": "Server or CDN configuration",
        "why_this_matters": "Pages that time out suggest slow server response, excessive resource loading, or network issues affecting analysis and real user visits.",
        "exact_correction": "Investigate the page load performance and address server-side or CDN issues causing the delay.",
        "implementation_steps": "1. Check server response times.\n2. Optimise slow database queries or API endpoints.\n3. Implement CDN caching.\n4. Reduce page weight and resource count.",
        "verification_steps": "1. Test page load time from multiple locations.\n2. Confirm analysis completes within the configured timeout.",
        "expected_result": "Faster page loads that complete within the configured analysis timeout.",
        "limitations": "Timeouts may be intermittent. A single timeout does not necessarily indicate a persistent issue.",
        "score_impact": 5,
    },
    "http_error": {
        "issue_title": "Page returned HTTP error status",
        "category": "technical",
        "severity": "high",
        "grouping_key": "http_error",
        "estimated_effort": "medium",
        "business_impact": "critical",
        "responsible_area": "backend",
        "responsible_role": "Developer",
        "action_location": "Page URL or server configuration",
        "why_this_matters": "HTTP error responses mean the page is not accessible. This can prevent users from reaching content and harms SEO if search engines encounter errors.",
        "exact_correction": "Investigate and fix the HTTP error (fix broken links, correct routing, fix server issues).",
        "implementation_steps": "1. Determine the specific HTTP error code.\n2. For 404: check if the URL path is correct or set up proper redirects.\n3. For 500: check server logs and fix the server-side error.\n4. For 403: check permissions and access control.\n5. Set up monitoring to detect recurring errors.",
        "verification_steps": "1. Visit the URL and confirm it returns a successful HTTP status (200-399).\n2. Check that the page renders correctly.",
        "expected_result": "The page will return a successful HTTP response and be accessible to users and crawlers.",
        "limitations": "Temporary HTTP errors may resolve on retry. Persistent errors require server-side investigation.",
        "score_impact": 20,
    },
}

SOURCE_MAP = {
    "lighthouse": "Lighthouse",
    "playwright": "Playwright",
    "http": "HTTP analysis",
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}


def _build_deterministic_grouping_key(finding_code: str, signal_suffix: str | None = None) -> str:
    if signal_suffix:
        return f"{finding_code}:{signal_suffix}"
    return finding_code


def _classify_confidence(confidence_percent: int) -> str:
    if confidence_percent >= 90:
        return "high"
    if confidence_percent >= 70:
        return "medium"
    if confidence_percent >= 40:
        return "low"
    return "unavailable"


def generate_actions(
    db: Session,
    website_id: uuid.UUID,
    page_analysis_execution_id: uuid.UUID,
    generation_execution_id: uuid.UUID | None = None,
) -> ActionGenerationExecution:
    if generation_execution_id is None:
        generation_execution_id = uuid.uuid4()

    existing = db.get(ActionGenerationExecution, generation_execution_id)
    if existing is not None:
        return existing

    execution = ActionGenerationExecution(
        id=generation_execution_id,
        website_id=website_id,
        page_analysis_execution_id=page_analysis_execution_id,
        status="running",
        started_at=datetime.now(UTC),
    )
    db.add(execution)
    db.flush()

    page_runs = list(
        db.scalars(
            select(PageAnalysisRun).where(
                PageAnalysisRun.page_analysis_execution_id == page_analysis_execution_id,
            )
        )
    )

    total_processed = 0
    total_generated = 0
    unsupported = 0
    insufficient = 0
    duplicates = 0
    historical = 0
    groups_cache: dict[str, ActionGroup] = {}

    for run in page_runs:
        if run.deep_analysis_run_id:
            findings = list(
                db.scalars(
                    select(AnalysisFinding).where(
                        AnalysisFinding.analysis_run_id == run.deep_analysis_run_id,
                    )
                )
            )
        else:
            findings = []

        recommendations = _generate_recommendations_from_run(db, run)

        for finding in findings:
            total_processed += 1
            mapping = FINDING_TO_ACTION_MAP.get(finding.finding_code)

            if mapping is None:
                unsupported += 1
                continue

            evidence = finding.evidence if isinstance(finding.evidence, dict) else {}
            if not evidence:
                insufficient += 1
                continue

            _create_or_update_action(
                db=db,
                execution=execution,
                website_id=website_id,
                run=run,
                finding=finding,
                mapping=mapping,
                groups_cache=groups_cache,
                confidence_percent=finding.confidence_percent,
                source_audit=SOURCE_MAP.get(finding.source, finding.source),
            )
            total_generated += 1

        for rec in recommendations:
            total_processed += 1
            identity = rec.get("finding_code", "") or rec.get("identity", "")
            if not identity:
                unsupported += 1
                continue

            mapping = FINDING_TO_ACTION_MAP.get(identity)
            if mapping is None:
                unsupported += 1
                continue

            evidence = rec.get("evidence", {})
            if not evidence:
                insufficient += 1
                continue

            _create_or_update_action(
                db=db,
                execution=execution,
                website_id=website_id,
                run=run,
                finding=None,
                mapping=mapping,
                groups_cache=groups_cache,
                evidence_override=evidence,
                finding_identity=identity,
                confidence_percent=rec.get("confidence_percent", 100),
                source_audit=rec.get("source", PAGE_ANALYSIS_SOURCE),
            )
            total_generated += 1

    for group in groups_cache.values():
        group.affected_page_count = len(group.actions)
        statuses = {a.status for a in group.actions}
        if len(statuses) == 1:
            group.status = statuses.pop()
        else:
            group.status = "mixed"

    execution.status = "completed"
    execution.completed_at = datetime.now(UTC)
    execution.total_findings_processed = total_processed
    execution.total_actions_generated = total_generated
    execution.unsupported_finding_count = unsupported
    execution.insufficient_evidence_count = insufficient
    execution.duplicate_within_execution_count = duplicates
    execution.historical_equivalent_count = historical
    db.flush()

    return execution


def _generate_recommendations_from_run(db: Session, run: PageAnalysisRun) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if run.status != "completed":
        if run.failure_reason_code:
            mapping = FAILURE_REASON_ACTION_MAP.get(run.failure_reason_code)
            if mapping:
                results.append(
                    {
                        "finding_code": f"FAILURE_{run.failure_reason_code.upper()}",
                        "identity": f"FAILURE_{run.failure_reason_code.upper()}",
                        "severity": mapping["severity"],
                        "evidence": {
                            "failure_code": run.failure_reason_code,
                            "failure_text": run.failure_reason_text,
                            "analysis_level": run.analysis_level,
                            "page_url": run.requested_url or run.final_url,
                        },
                        "confidence_percent": 100,
                        "source": PAGE_ANALYSIS_SOURCE,
                    }
                )
        return results

    signals = run.basic_seo_signals
    if signals.get("no_h1"):
        results.append(
            {
                "finding_code": "MISSING_H1",
                "identity": "MISSING_H1",
                "evidence": {"h1_count": 0, "page_url": run.final_url or run.requested_url},
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )
    if signals.get("multiple_h1"):
        results.append(
            {
                "finding_code": "MULTIPLE_H1",
                "identity": "MULTIPLE_H1",
                "evidence": {
                    "h1_count": signals.get("h1_count", 0),
                    "page_url": run.final_url or run.requested_url,
                },
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )
    if not signals.get("has_title"):
        results.append(
            {
                "finding_code": "MISSING_PAGE_TITLE",
                "identity": "MISSING_PAGE_TITLE",
                "evidence": {
                    "page_title": run.page_title,
                    "page_url": run.final_url or run.requested_url,
                },
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )
    if not signals.get("has_meta_description"):
        results.append(
            {
                "finding_code": "MISSING_META_DESCRIPTION",
                "identity": "MISSING_META_DESCRIPTION",
                "evidence": {
                    "meta_description": run.meta_description,
                    "page_url": run.final_url or run.requested_url,
                },
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )
    if not signals.get("has_canonical"):
        results.append(
            {
                "finding_code": "MISSING_CANONICAL_URL",
                "identity": "MISSING_CANONICAL_URL",
                "evidence": {"canonical_url": None, "page_url": run.final_url or run.requested_url},
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )

    a11y = run.basic_accessibility_signals
    images_missing = a11y.get("images_missing_alt", 0) or 0
    if images_missing > 0:
        results.append(
            {
                "finding_code": "IMAGES_MISSING_ALT",
                "identity": "IMAGES_MISSING_ALT",
                "evidence": {
                    "images_missing_alt": images_missing,
                    "page_url": run.final_url or run.requested_url,
                },
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )
    if not a11y.get("has_html_lang"):
        results.append(
            {
                "finding_code": "MISSING_HTML_LANGUAGE",
                "identity": "MISSING_HTML_LANGUAGE",
                "evidence": {
                    "html_language": run.language,
                    "page_url": run.final_url or run.requested_url,
                },
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )

    security = run.security_observations
    if not security.get("https"):
        results.append(
            {
                "finding_code": "NON_HTTPS_WEBSITE",
                "identity": "NON_HTTPS_WEBSITE",
                "evidence": {"https": False, "page_url": run.final_url or run.requested_url},
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )
    if not security.get("x_frame_options"):
        results.append(
            {
                "finding_code": "MISSING_X_FRAME_OPTIONS",
                "identity": "MISSING_X_FRAME_OPTIONS",
                "evidence": {
                    "x_frame_options": security.get("x_frame_options"),
                    "page_url": run.final_url or run.requested_url,
                },
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )
    if not security.get("x_content_type_options"):
        results.append(
            {
                "finding_code": "MISSING_X_CONTENT_TYPE_OPTIONS",
                "identity": "MISSING_X_CONTENT_TYPE_OPTIONS",
                "evidence": {
                    "x_content_type_options": security.get("x_content_type_options"),
                    "page_url": run.final_url or run.requested_url,
                },
                "confidence_percent": 100,
                "source": PAGE_ANALYSIS_SOURCE,
            }
        )

    return results


def _create_or_update_action(
    db: Session,
    execution: ActionGenerationExecution,
    website_id: uuid.UUID,
    run: PageAnalysisRun,
    finding: AnalysisFinding | None,
    mapping: dict[str, Any],
    groups_cache: dict[str, ActionGroup],
    evidence_override: dict[str, Any] | None = None,
    finding_identity: str | None = None,
    confidence_percent: int = 100,
    source_audit: str = PAGE_ANALYSIS_SOURCE,
) -> ActionItem:
    identity = finding_identity or (finding.finding_code if finding else mapping["grouping_key"])
    evidence = (
        evidence_override
        if evidence_override is not None
        else (finding.evidence if finding else {})
    )

    priority_score_val, priority_components = calculate_priority_score(
        severity=mapping["severity"],
        affected_page_count=1,
        estimated_score_impact=mapping["score_impact"],
        confidence_percent=confidence_percent,
        implementation_effort=mapping["estimated_effort"],
        business_impact=mapping["business_impact"],
    )

    confidence_label = _classify_confidence(confidence_percent)

    group_key = f"{mapping['grouping_key']}"
    group = groups_cache.get(group_key)
    if group is None:
        group = ActionGroup(
            generation_execution_id=execution.id,
            website_id=website_id,
            grouping_key=group_key,
            issue_title=mapping["issue_title"],
            category=mapping["category"],
            severity=mapping["severity"],
            priority_score=priority_score_val,
            priority_formula_version="1.0.0",
            confidence=confidence_label,
            estimated_effort=mapping["estimated_effort"],
            business_impact=mapping["business_impact"],
            responsible_area=mapping["responsible_area"],
            responsible_role=mapping["responsible_role"],
            action_location=mapping["action_location"],
            why_this_matters=mapping["why_this_matters"],
            exact_correction=mapping["exact_correction"],
            implementation_steps=mapping["implementation_steps"],
            verification_steps=mapping["verification_steps"],
            expected_result=mapping["expected_result"],
            limitations=mapping["limitations"],
            evidence_summary=evidence,
            source_audit=source_audit,
            priority_components=priority_components,
            affected_page_count=0,
            status="open",
        )
        db.add(group)
        db.flush()
        groups_cache[group_key] = group

    existing_action = db.scalar(
        select(ActionItem).where(
            ActionItem.generation_execution_id == execution.id,
            ActionItem.source_finding_identity == identity,
            ActionItem.website_page_id == run.website_page_id,
        )
    )
    if existing_action is not None:
        return existing_action

    item = ActionItem(
        generation_execution_id=execution.id,
        action_group_id=group.id,
        website_id=website_id,
        page_analysis_run_id=run.id,
        website_page_id=run.website_page_id,
        source_finding_identity=identity,
        source_page_analysis_run_id=run.id,
        requested_url=run.requested_url or run.final_url,
        final_url=run.final_url or run.requested_url,
        page_title=run.page_title,
        issue_title=mapping["issue_title"],
        issue_category=mapping["category"],
        severity=mapping["severity"],
        priority_score=priority_score_val,
        priority_formula_version="1.0.0",
        priority_components=priority_components,
        confidence=confidence_label,
        confidence_percent=confidence_percent,
        estimated_effort=mapping["estimated_effort"],
        business_impact=mapping["business_impact"],
        responsible_area=mapping["responsible_area"],
        responsible_role=mapping["responsible_role"],
        action_location=mapping["action_location"],
        why_this_matters=mapping["why_this_matters"],
        exact_correction=mapping["exact_correction"],
        implementation_steps=mapping["implementation_steps"],
        verification_steps=mapping["verification_steps"],
        expected_result=mapping["expected_result"],
        limitations=mapping["limitations"],
        evidence_summary=evidence,
        source_audit=source_audit,
        status="open",
    )
    db.add(item)
    db.flush()

    history = ActionStatusHistory(
        action_item_id=item.id,
        previous_status="",
        new_status="open",
        source="system",
    )
    db.add(history)

    return item
