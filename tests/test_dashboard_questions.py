"""Readable questions still navigate to and answer the original stored record."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from tests import test_code_workflow as fixtures
from verif_harness.dashboard import dashboard_project_id


ROOT = Path(__file__).resolve().parents[1]


class DashboardQuestionsTest(unittest.TestCase):
    def test_question_copy_uses_plain_language(self):
        html = (ROOT / 'verif_harness/dashboard.html').read_text()
        for phrase in ('绑定', '分片', '补洞闭环结果', '结构性不可达', '证据结构合同冲突'):
            self.assertNotIn(phrase, html)
        self.assertNotIn('Agent 需要你确认：${escapeHtml(question.prompt)}', html)

    def test_browser_long_questions_and_answer_persistence(self):
        self.run_question_script('dashboard_questions.cjs', 'playwright')

    def test_dom_long_questions_and_answer_persistence(self):
        self.run_question_script('dashboard_questions_dom.cjs', 'jsdom')

    def run_question_script(self, script, module):
        if not shutil.which('node') or subprocess.run(
            ['node', '-e', f"require('{module}')"], capture_output=True,
        ).returncode:
            self.skipTest(f'Node.js and {module} are required for this DOM test')
        fixture = fixtures.CodeWorkflowTest()
        fixture.setUp()
        try:
            options = [
                {'id': 'current', 'label': '继续检查当前接口',
                 'description': '检查已列出的输入和输出。\n\n- 保留现有范围\n- 继续检查测试结果'},
                {'id': 'extend', 'label': '增加检查内容', 'description': '先更新方案，再继续检查。'},
            ]
            prompt = '【请确认接口检查范围】' + '当前测试结果已记录，需要确认是否增加检查内容。' * 20
            context = (
                '## 当前结果\n\n- 公开样例测试已完成\n- 还需确认检查范围\n\n'
                '## 示例命令\n\n```sh\necho "<fixture>"\n```\n\n'
                '<img src=x onerror="window.questionInjected=true">'
            )
            question = fixture.store.ask_agent_question(
                fixture.plan_node['id'], prompt, options, 'current', context,
            )
            second = fixture.store.ask_agent_question(
                fixture.plan_node['id'], '请确认是否检查复位后的接口状态', options,
            )
            f = fixture.fixture.fixture
            config = {
                'url': f.url, 'project': dashboard_project_id(fixture.root),
                'token': f.server.write_token, 'node': fixture.plan_node['id'],
                'question': question['id'], 'second': second['id'],
                'prompt': prompt, 'context': context,
            }
            result = subprocess.run(
                ['node', str(ROOT / 'tests' / script)],
                input=json.dumps(config), text=True, capture_output=True,
                timeout=90, env=os.environ.copy(),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            saved = fixture.store.agent_question(question['id'])
            self.assertEqual(saved['status'], 'ANSWERED')
            self.assertEqual(saved['answer_option'], 'current')
            self.assertEqual(saved['prompt'], prompt)
            self.assertEqual(saved['context'], context)
            self.assertEqual(fixture.store.agent_question(second['id'])['status'], 'OPEN')
            self.assertFalse(fixture.store.node_plan_review_state(fixture.plan_node['id'])['completed'])
            print(result.stdout.strip())
        finally:
            fixture.tearDown()
