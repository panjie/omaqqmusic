import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UiContractTests(unittest.TestCase):
    def test_dynamic_text_uses_plain_label(self):
        component = (ROOT / 'PlainLabel.qml').read_text()
        self.assertIn('textFormat: Text.PlainText', component)
        for name in ('NativePanel.qml', 'BarWidget.qml'):
            source = (ROOT / name).read_text()
            self.assertNotRegex(source, r'\bText\s*\{')
            self.assertNotIn('showTooltip', source)
            for line in source.splitlines():
                if 'tooltipText:' in line:
                    self.assertRegex(line, r'tooltipText: strings\.t\(')
                if re.search(r'^\s+text:', line) and ('modelData' in line or 'state.account' in line):
                    # Dynamic labels belong to PlainLabel; never to the shared Button.
                    prefix = source[:source.index(line)]
                    self.assertGreater(prefix.rfind('PlainLabel {'), prefix.rfind('Button {'))

    def test_all_error_and_login_states_are_translated(self):
        en = json.loads((ROOT / 'i18n/en.json').read_text())
        chinese = [json.loads((ROOT / 'i18n' / f'{locale}.json').read_text())
                   for locale in ('zh', 'zh-CN')]
        for catalog in chinese:
            self.assertEqual(set(en), set(catalog))
        self.assertTrue(all(catalog == chinese[0] for catalog in chinese[1:]))
        for file in (ROOT / 'backend').glob('*.py'):
            for key in re.findall(r"UserError\('([a-z_]+)'\)", file.read_text()):
                self.assertIn('error_' + key, en)
        for status in ('waiting', 'scanned', 'success', 'expired', 'failed'):
            self.assertIn('login_' + status, en)

    def test_service_is_shared_and_native(self):
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        self.assertIn('service', manifest['kinds'])
        self.assertTrue(manifest['keepLoaded'])
        source = (ROOT / 'BarWidget.qml').read_text()
        self.assertIn('serviceFor(moduleName)', source)
        self.assertNotIn('openUrlExternally', source)
        self.assertNotIn('Mpris', source)


if __name__ == '__main__':
    unittest.main()
