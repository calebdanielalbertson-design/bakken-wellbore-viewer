# Desktop viewer usability review

Reviewed October 20, 2026. Scope: audit and a discussion mockup before implementing a desktop sidebar redesign. No deployed viewer files changed.

## Observed current behavior

Read the deployed viewer DOM at https://bakkensubsurface.com/viewer/?dataset=full and the current local source under sites/bakken-subsurface/dist/viewer. At 1280 × 720, the sidebar is 644 px high and contains 2,681 px of content before expanding DSU or inventory controls. The search begins 251 px down the sidebar; selected-well information begins at 2,017 px; the section legend begins at 2,159 px. These measurements describe this loaded default session, not all viewport sizes or states.

- The sidebar follows feature-addition order. Well colors are near the top, but section visibility, the section legend and trajectory refinements are near the bottom. Search is separated from its selection details by several unrelated features. See viewer/index.html and app.js select()/renderSelection().
- The DSU color selector and the footage metric selector both control DSU footage colors. footage.js applyVisibility() and dsu.js useFootageMetric()/footageRequested() synchronize them, but their UI relationship is hard to discover.
- Desktop footage geography switches DSU/township visibility. After entering the mobile breakpoint, independent-layer behavior persists when returning to desktop. See footage.js useIndependentLayers()/applyVisibility() and mobile-controls.js resize(). This needs one explicit state model, rather than a CSS-only cleanup.
- Separate DSU and township inspection toggles determine what clicks do. DSU inspection takes priority and consumes misses as well. See app.js pointer selection routing, dsu.js inspection and footage.js picking.
- Operator filtering initially becomes discoverable through Operator coloring. An active operator filter correctly remains visible in other color modes, but brings its lengthy operator legend with it. See survey-colors.js legend(). Filtering should be independently discoverable; legends should follow the active color mode.
- Production automatically enables after matched data load. Unchecking production does not collapse all sidebar settings. The default production timeline covers a substantial part of the map. See production.js load()/setEnabled().
- Plan view and Fit North Dakota both invoke viewState(), so changing camera orientation can discard a local framing. See app.js top/fitState handlers.
- The public Well logs section is an availability notice rather than a usable control. Sample dataset and Open dataset folder are prominent header actions. Move those into data/help settings.

## Proposed organization

1. **Persistent search:** Find a well by name, file number or API. Keep active filters visible and make clear when they constrain results. Empty results should offer a clear-filter action.
2. **Compact selected-item card:** identity, Zoom to selection, Clear and expandable details. Reuse this location for well, DSU and township selection. Large production charts and branch metadata must not push the main navigation away.
3. **Three task tabs:**
   - **Wells:** color mode, independently available operator filter, matching legend and path/section filters. Keep custom scales and trajectory comparison under Advanced.
   - **Areas:** DSUs or townships, one relevant color/measure control, low/base/high scenario when applicable, path emphasis and explicit selection target. Keep overlapping outlines, opacity, provisional depths, density edits and the historical model in Advanced. Preserve the ability to show DSU outlines with townships as an explicit advanced option.
   - **Production:** opt-in size overlay, playback/date controls, current scope and coverage. Size calibration and source details expand on demand. Opening or closing the tab must not silently change playback or filters; the enable control owns that state.
4. **View & data settings:** reference plane, vertical exaggeration, dataset tools, source details and methodology. Put camera orientation and framing controls above the map, outside the sidebar.
5. **Compact persistent state summary:** active operator filter, selection target and enabled overlays. Provide a clear reset action that returns camera and controls to documented defaults.

## Interaction rules

- Orientation changes (Plan / 3D / Side) retain the selected location and sensible local framing. Fit visible, Fit North Dakota and Zoom to selection are separate actions.
- There is one current selection target: wells, DSUs or townships. Only visible/selectable layer types can be picked. Show that target where users can see it while clicking the map.
- Tabs reveal tools; they do not reset camera, selection, filters or active layers. Selected-item actions remain discoverable across tabs.
- Use a common controller for desktop and mobile so resizing does not change layer semantics. Preserve mobile's existing quick controls and production-collapse behavior.
- Keep survey-derived and scenario limitations beside the affected value or legend: approximate depths, historical model label, inventory scope (all surveyed operators), missing production values versus zero. Put long explanations under methodology, not essential context.
- Recommended default: Well section colors, all operators, state reference visible, no area overlays, production collapsed/off. Respect an explicit shared-link state instead of overriding it with defaults.
- The concept uses three common color shortcuts plus a synchronized full selector; this is optional. Do not duplicate underlying state or reproduce the current two-controller DSU confusion.

## Implementation phases

1. **Local layout prototype:** reorganize existing DOM controls and retain their IDs, data attributes and event wiring. Add the selected-item card and task navigation. No data/classifier changes. Use the real viewer and current snapshot for review.
2. **State/interaction cleanup:** make layer visibility, selection target, reset and desktop/mobile synchronization explicit; decouple camera orientation from geographic fitting; make production opt-in except when requested by a shared link.
3. **Validation and release:** test real discovery tasks at desktop, laptop, keyboard and mobile sizes, then publish the reviewed version through the established Sites workflow. Preserve the previous release for comparison.

## Acceptance tasks

Ask a person unfamiliar with the viewer to do these without coaching. Observe where they hesitate; these are validation goals, not claims already demonstrated.

- Find A. Johnson by name, zoom to the well and locate its details without searching down the sidebar.
- Change between Operator, Well section and DLS, identify the legend and remove a filter.
- Display a DSU, select it, understand which wells belong to the selected group and find combined production.
- Change to township development, identify Base as an assumption, make well paths faint, then return to selecting wells.
- Enable monthly oil, identify the date/coverage and group scope, play/pause and close the overlay.
- Change to Plan view without losing the current local area; then deliberately fit North Dakota.
- Resize across 800 px and 560 px and back: layer state and click target must remain consistent. Verify deep links, reset, missing-data states, focus order and all existing calculations/production results.

## Discussion concept

The conversation-only mockup is viewer-sidebar-concept.html in this thread's visualization directory. It demonstrates task tabs, adjacent legends, operator filter, area controls, production disclosure and a sample A. Johnson selection. It contains no live dataset or map renderer; preview actions must not be interpreted as implemented viewer behavior. EOR remains a separate project section and should not add another block to this sidebar.


## Implemented October 20, 2026

User approved implementation and direct publication. The production release now uses `dist/sidebar.js` and `dist/sidebar.css` to move the original controls, preserving IDs and existing controller wiring. Wells, Areas and Production tabs expose one task at a time; search, selected-item actions, map selection target and active operator filter remain above them. Dataset and advanced controls use disclosures. The previous published version remains available as V7.

- `app.js`: explicit well / DSU / township click target; compact selected-item controller; unified area choice; empty-search filter recovery; reset; Fit visible from displayed segment and area bounds. Well searches clear an unrelated DSU production scope; choosing a member from a DSU list retains group context.
- `navigation.js`: orientation changes preserve the current target and apparent world scale, including target depth; North Dakota, Fit visible and Zoom remain explicit framing actions.
- `footage.js` and `mobile-controls.js`: consistent independent layer visibility across desktop/mobile, selected township APIs, user-selection versus redraw events, and hidden-layer load protection.
- `production.js`: overlay starts off unless explicitly requested by the URL/showcase or the user. Tab changes do not toggle or pause production. Mobile explicit enable/Play opens playback; resizing does not change it.

Validation performed with the full public snapshot: A. Johnson 35721 search/zoom, local Plan/3D/Side views, DLS and operator filter recovery, DSU #67 selection with 11 associated wells and combined monthly history, township T152N R96W with High scenario, mobile 390px and desktop 1280px transitions, and reset defaults. No browser JavaScript errors were observed in these flows. Browser accessibility checks cover tab keyboard navigation, preservation of original IDs, no duplicate IDs, and no horizontal overflow. This is engineering QA; first-time user testing is still useful.

Focused checks: `work/test_navigation.mjs` (300 orientation transitions and existing deep-zoom checks), `scripts/test_viewer_controller_state.mjs`, and `scripts/test_production_well_context.mjs`. Public `validate_release.py` and `test_public_transport.mjs` verify all 450 compressed logical assets and their restored bytes. No classification, geometry, scenario formula or production observations were changed by this interface update. Premium production ingestion, EOR and backend staging remain separate work.


### Publication

Published successfully as Sites V8 on 2026-10-20 at 22:40 UTC. Source commit: `8a67ef5d3988be6986b4a6bbd76e9f8a30da5d3b`. Deployment: `appgdep_6ad7eddbf17081918a6bfc199df1c34f`. Public viewer: https://bakkensubsurface.com/viewer/. Provider URL: https://bakken-subsurface.briny-stoat-5178.chatgpt.site. Archive validation: 533 static files, 233,962,156 bytes; 450 compressed logical assets verified. The optimized reset and unrelated-well scope clearing were retested in the browser successfully before packaging.
