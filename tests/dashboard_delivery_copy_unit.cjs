// Use the shipped Dashboard functions with synthetic report text; no state write.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../verif_harness/dashboard.html'), 'utf8')
  .match(/<script>([\s\S]*?)<\/script>/)[1];
const context = vm.createContext({assert, URL, URLSearchParams,
  window:{location:{search:'',href:'http://dashboard.invalid/'}},
  localStorage:{getItem:() => '', setItem:() => {}},
  document:{querySelector:() => ({content:'fixture-token'}), querySelectorAll:() => []},
});
vm.runInContext(source.slice(0, source.indexOf("    $('#drawer-backdrop').onclick")), context);
vm.runInContext(String.raw`
  (() => {
    const raw = '本轮报告与测试绑定；检查 4 个分片。未覆盖项按结构性不可达分析；报告存在证据结构合同冲突。';
    const output = deliverySummaryHtml(raw);
    const visible = output.split('<details>')[0];
    assert.equal((visible.match(/<li>/g) || []).length, 4);
    assert.match(visible, /本轮报告与测试对应/);
    assert.match(visible, /4 个分批生成的数据/);
    assert.match(visible, /按当前设计不会发生/);
    assert.match(visible, /报告与当前检查要求不一致/);
    assert.doesNotMatch(visible, /绑定|分片|结构性不可达|证据结构合同冲突/);
    assert.match(output, /<pre>本轮报告与测试绑定；/);
    assert.equal(raw.includes('绑定'), true);

    const criterion = '文件路径与 SHA-256 绑定当前 VCOV revision 与本节点范围';
    assert.equal(ownerFacingProse(criterion), '排除文件的路径和文件摘要与当前覆盖率方案版本及本节点检查范围一致');
    assert.equal(ownerFacingProse('两类证据均绑定当前收敛清单'), '两项检查结果使用同一份当前覆盖对象清单');
    assert.equal(ownerFacingProse('证据结构合同冲突：控制面要求三个清单，已批准方案使用一个清单'),
      '系统检查要求与已批准方案不一致：控制面要求三个清单，已批准方案使用一个清单');
    assert.equal(ownerFacingProse('命令：\x60绑定\x60'), '命令：\x60绑定\x60');
    assert.equal(ownerFacingProse('命令：\x60\x60\x60sh\n绑定位置信息\n\x60\x60\x60'), '命令：\x60\x60\x60sh\n绑定位置信息\n\x60\x60\x60');

    const node = {workstream:'VCOV', role:'coverage-convergence-deliverable',
      coverage_collection_config:{schema:'CoverageCollectionConfig/1',
        regression_sources:[{}], merge_profile:{path:'merge.json',tool:{name:'urg',version:'1'}},
        dut_build_fingerprint:{dut_design_id:'demo-dut'}},
      plan_review:{coverage_regression_sources:[{regression_group:'group-a',submit_profile_id:'profile-a'}]}};
    const validation = {current:true,ready:false,summary:raw,code_files:[],
      files:[{path:'inventory.json',sha256:'inventory-digest'}],checks:[
        {claim:'coverage-collection-evidence',criterion:'结果绑定本次测试',method:'核对报告',
          expected:'一致',actual:'一致',validation:{ready:true,facts:{}}},
        {claim:'hole-analysis-evidence',criterion:'未覆盖项已分析',method:'核对报告',
          expected:'全部说明',actual:'仍有 1 项',validation:{ready:false,facts:{
            required_objects:4,covered_objects:2,uncovered_objects:1,excluded_objects:1,
            coverage_inventory_digest:'inventory-digest',kind_counts:{line:2,'coverpoint-bin':2},
            holes:[{object_key:'CASE.1',status:'uncovered',responsible_workstream:'VCASE',next_action:'增加测试'},
              {object_key:'CASE.2',status:'excluded',waiver:{rationale:'按当前设计不会发生'}}]}}},
      ]};
    const page = coverageConvergenceDeliveryHtml(node,validation,'<div>排除文件入口</div>',
      file => '<button>' + file.path + '</button>');
    for (const heading of ['1. 检查范围','2. 结果报告','3. 未覆盖项说明','4. 排除项说明','5. 检查与验收']) {
      assert.ok(page.includes(heading));
    }
    assert.ok(page.indexOf('1. 检查范围') < page.indexOf('5. 检查与验收'));
    assert.match(page, /demo-dut/);
    assert.match(page, /group-a/);
    assert.match(page, /功能覆盖点 2 项/);
    assert.match(page, /inventory.json/);
    assert.match(page, /<strong>4<\/strong><span>要求检查/);
    assert.match(page, /<strong>1<\/strong><span>未覆盖/);
    assert.match(page, /CASE.1/);
    assert.match(page, /负责处理：.*用例/);
    assert.match(page, /下一步：增加测试/);
    assert.match(page, /CASE.2/);
    assert.match(page, /排除文件入口/);
    assert.match(page, /当前不能验收/);
    assert.doesNotMatch(page.split('查看报告原文')[0], /绑定|分片|补洞闭环结果|结构性不可达|证据结构合同冲突/);
  })();
`, context);
console.log('Delivery summary breaks into readable items; raw report stays available PASS');
