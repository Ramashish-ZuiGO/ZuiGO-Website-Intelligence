// M3 canonical responsive-assertion contract (docs/DEVICE_OS_BROWSER_QA_PLAN.md).
//
// Single source of truth for "what does broken responsive mean", shared
// between the Python worker (embedded via page.evaluate in
// browser_compatibility.py) and the Node.js GitHub Actions Tier 0 script
// (.github/scripts/browser_uat_tier0_check.mjs). Both Playwright bindings
// accept a JS function-expression string for page.evaluate(expr, arg), so
// this file's exported shape is that expression, called with [name, width,
// height].
//
// Four deterministic, per-viewport checks, plus two raw per-viewport data
// points (nav_visible_item_count, has_navigation_toggle) that feed a FIFTH,
// cross-viewport check -- whether navigation genuinely adapts across
// viewports rather than just shrinking. That comparison itself does not fit
// a single page.evaluate() call (it needs BOTH a Desktop and a Mobile
// result to compare), so it is NOT computed here -- see
// compute_responsive_navigation_adapts() in browser_compatibility.py, which
// consumes these two raw fields from a pair of per-viewport calls to this
// module.
//
//   1. horizontal_overflow    -- page content wider than the viewport
//   2. clipped_elements       -- critical elements extending past the edges
//   3. overlapping_elements   -- visible elements whose boxes collide
//   4. small_tap_targets      -- interactive elements below the WCAG 2.5.5
//                                24x24 CSS px minimum, with a spacing
//                                exception for adjacent elements

(([name, width, height]) => {
  const CRITICAL_SELECTOR = "nav, main, h1, button, input";
  const INTERACTIVE_SELECTOR = 'button, a[href], input, select, textarea, [role="button"]';
  const MIN_TAP_TARGET_PX = 24;
  const EDGE_TOLERANCE_PX = 2;

  const isVisible = (node) => {
    const style = getComputedStyle(node);
    const box = node.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };

  const boxesIntersect = (a, b) =>
    !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);

  const describeElement = (node) =>
    (
      node.getAttribute("aria-label") ||
      node.getAttribute("title") ||
      node.textContent ||
      node.value ||
      node.tagName.toLowerCase()
    )
      .trim()
      .slice(0, 120);

  const horizontalOverflow = document.documentElement.scrollWidth > width;

  const criticalNodes = [...document.querySelectorAll(CRITICAL_SELECTOR)].filter(isVisible);
  const clipped = criticalNodes.filter((node) => {
    const box = node.getBoundingClientRect();
    return box.right > width + EDGE_TOLERANCE_PX || box.left < -EDGE_TOLERANCE_PX;
  });

  const overlapCandidates = criticalNodes
    .concat([...document.querySelectorAll(INTERACTIVE_SELECTOR)].filter(isVisible))
    .filter((node, index, all) => all.indexOf(node) === index);
  const overlapping = [];
  for (let i = 0; i < overlapCandidates.length; i += 1) {
    for (let j = i + 1; j < overlapCandidates.length; j += 1) {
      const nodeA = overlapCandidates[i];
      const nodeB = overlapCandidates[j];
      if (nodeA.contains(nodeB) || nodeB.contains(nodeA)) continue;
      if (boxesIntersect(nodeA.getBoundingClientRect(), nodeB.getBoundingClientRect())) {
        overlapping.push([nodeA, nodeB]);
      }
    }
  }

  const interactiveNodes = [...document.querySelectorAll(INTERACTIVE_SELECTOR)]
    .map((node) => ({ node, box: node.getBoundingClientRect() }))
    .filter((item) => isVisible(item.node));
  const smallTargets = interactiveNodes.filter(
    (item) => item.box.width < MIN_TAP_TARGET_PX || item.box.height < MIN_TAP_TARGET_PX,
  );
  const tapTargetSamples = smallTargets.slice(0, 20).map((item) => {
    const padX = Math.max(0, (MIN_TAP_TARGET_PX - item.box.width) / 2);
    const padY = Math.max(0, (MIN_TAP_TARGET_PX - item.box.height) / 2);
    const expanded = {
      left: item.box.left - padX,
      right: item.box.right + padX,
      top: item.box.top - padY,
      bottom: item.box.bottom + padY,
    };
    const spacingException = !interactiveNodes.some(
      (other) => other.node !== item.node && boxesIntersect(other.box, expanded),
    );
    return {
      element_type: item.node.tagName.toLowerCase(),
      accessible_label: describeElement(item.node),
      width: item.box.width,
      height: item.box.height,
      spacing_exception: spacingException,
    };
  });

  // Raw per-viewport navigation data for the 5th, cross-viewport check (see
  // module header). Heuristic, not exhaustive -- real sites mark up
  // navigation wildly differently, so this favors standard, documented
  // signals (aria-expanded is the canonical a11y pattern for a collapsible
  // toggle control) over guessing at CSS class names alone.
  const NAV_SELECTOR = 'nav, [aria-label*="navigation" i]';
  const NAV_ITEM_SELECTOR = 'a[href], [role="menuitem"]';
  const NAV_TOGGLE_SELECTOR =
    'button[aria-expanded], [aria-label*="menu" i], [class*="hamburger" i], ' +
    '[class*="menu-toggle" i], [class*="nav-toggle" i]';

  const navElements = [...document.querySelectorAll(NAV_SELECTOR)];
  const navVisibleItemCount = navElements
    .flatMap((nav) => [...nav.querySelectorAll(NAV_ITEM_SELECTOR)])
    .filter(isVisible).length;
  const hasNavigationToggle = [...document.querySelectorAll(NAV_TOGGLE_SELECTOR)].some(isVisible);

  const problems = [];
  if (horizontalOverflow) {
    problems.push(
      "Page content overflows the viewport horizontally, requiring horizontal scrolling.",
    );
  }
  if (clipped.length > 0) {
    problems.push(
      `${clipped.length} critical element(s) extend beyond the visible viewport width.`,
    );
  }
  if (overlapping.length > 0) {
    problems.push(`${overlapping.length} element(s) overlap unexpectedly at this viewport size.`);
  }
  const targetsWithoutSpacingException = tapTargetSamples.filter(
    (sample) => !sample.spacing_exception,
  ).length;
  if (targetsWithoutSpacingException > 0) {
    problems.push(
      `${targetsWithoutSpacingException} interactive element(s) are smaller than the ` +
        `${MIN_TAP_TARGET_PX}x${MIN_TAP_TARGET_PX}px minimum tap-target size with insufficient spacing.`,
    );
  }

  return {
    name,
    width,
    height,
    status: "passed",
    horizontal_overflow: horizontalOverflow,
    critical_elements_outside_viewport: clipped.length,
    overlapping_elements: overlapping.length,
    responsive_navigation: Boolean(document.querySelector('nav, [aria-label*="navigation" i]')),
    nav_visible_item_count: navVisibleItemCount,
    has_navigation_toggle: hasNavigationToggle,
    small_tap_targets: smallTargets.length,
    tap_target_samples: tapTargetSamples,
    viewport_problems: problems,
  };
})
