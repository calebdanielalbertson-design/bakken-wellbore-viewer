"""Offline guards and visibility behavior for the actual in-memory app hooks."""
from pathlib import Path
import subprocess
import unittest

from preview_hooks import transform_app, TIMELINE_GUARDS

WORKSPACE = Path(__file__).resolve().parents[3]
APP = WORKSPACE / "sites/bakken-subsurface/dist/viewer/app.js"


def node(script: str, *, check: bool = False):
    arguments = ["node", "--input-type=module"]
    if check:
        arguments.append("--check")
    result = subprocess.run(arguments, input=script, text=True, encoding="utf-8", capture_output=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr + result.stdout)


class Hooks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = APP.read_text(encoding="utf-8")
        cls.app = transform_app(cls.original)

    def test_source_drift_and_duplicate_application_fail(self):
        with self.assertRaisesRegex(ValueError, "decorate-all-sections"):
            transform_app(self.original.replace("if(section===4)production.decorate(l);", "/* changed */"))
        with self.assertRaisesRegex(ValueError, "decorate-all-sections"):
            transform_app(self.app)
        with self.assertRaisesRegex(ValueError, "decorate-all-sections"):
            transform_app(self.original + "\nif(section===4)production.decorate(l);")

    def test_actual_app_syntax_and_local_bridge_anchor(self):
        node(self.app, check=True)
        self.assertEqual(self.app.count("const requestedColor=new URLSearchParams(location.search).get('color');"), 1)
        self.assertEqual(transform_app(self.original.replace("\n", "\r\n")).replace("\r\n", "\n"), self.app)

    def test_fit_ignores_hidden_paths_and_gamma(self):
        implementation = self.app.split("function fitVisible(){", 1)[1].split("function visibleSpan()", 1)[0]
        node("""
import assert from 'node:assert/strict';
const manifest={wells:[{id:0},{id:1}]},detail=new Map(),viewOrientation='plan';
const overviewLines=[{visible:true,userData:{ids:[0,1]},geometry:{attributes:{position:{array:[1,2,3,4,5,6,900,900,900,999,999,999]}}}}];
const production={visible:w=>w?.id===0,activityActive:()=>true};
const dsu={visibleBounds:()=>null},footage={visibleBounds:()=>null};
const gamma={enabled:()=>true,limits:()=>{throw Error('Hidden gamma affected fit');}};
let fitted=null;const fit=(bounds,view)=>{fitted={bounds,view};},say=()=>{};
function fitVisible(){
""" + implementation + """
fitVisible();
assert.deepEqual(fitted,{bounds:[1,2,3,4,5,6],view:'plan'});
""")

    def test_hidden_selection_cannot_create_an_overlay(self):
        implementation = self.app.split("function renderSelection(){", 1)[1].split("function wellScope", 1)[0]
        node("""
import assert from 'node:assert/strict';
let disposed=0,highlight={},selected={id:3},selectedData=new Float32Array([1,2,3,4]);
const dispose=()=>disposed++,production={visible:()=>false};
const root={add:()=>{throw Error('Hidden selection created an overlay');}};
function renderSelection(){
""" + implementation + """
renderSelection();assert.equal(highlight,null);assert.equal(disposed,1);
""")

    def test_timeline_lifecycle_and_gamma_fallback(self):
        node("""
import assert from 'node:assert/strict';
let active=true,gammaActive=true,manifest=null,selected={id:1};
const events=new Map(),calls=[];
const hover={hidden:false};
const toggle={disabled:false,checked:true,dispatchEvent(){gammaActive=this.checked;}};
const $=id=>id==='gammaEnabled'?toggle:id==='gammaHover'?hover:null;
const gamma={enabled:()=>gammaActive,group:{visible:true}};
const production={activityActive:()=>active,visible:()=>false};
const document={addEventListener:(name,callback)=>events.set(name,callback)};
const clearSelection=()=>{calls.push('clear');selected=null;};
const renderWellSearch=()=>calls.push('search'),refreshDSUHighlight=()=>calls.push('dsu');
const renderSelection=()=>calls.push('selection'),syncGammaContext=()=>calls.push('gamma');
""" + TIMELINE_GUARDS + """
const changed=events.get('viewer:timeline-changed');changed();
assert.equal(gammaActive,false);assert.equal(toggle.disabled,true);assert.equal(hover.hidden,true);
assert.equal(gamma.group.visible,false);assert.deepEqual(calls,[],'manifest-null load safe');
manifest={wells:[]};changed();assert.deepEqual(calls,['clear','search','dsu','selection','gamma']);
active=false;changed();assert.equal(toggle.disabled,false);
assert.equal(gammaActive,false,'timeline exit does not unexpectedly enable logs');
""")


if __name__ == "__main__":
    unittest.main()
