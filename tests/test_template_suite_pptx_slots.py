import unittest
from bs4 import BeautifulSoup
from landppt.services.template.template_suite_service import TemplateSuiteService

class SuitePptxSlotsTest(unittest.TestCase):
    def test_fixed_and_mixed_text(self):
        raw = '<html><head><style>h1{font:40px Georgia}</style></head><body><!-- {{comment_only}} --><div>FIXED BRAND</div><h1>{{ cover_title }}</h1><p>第{{chapter_number}}章</p></body></html>'
        suite = {key: raw for key in ('cover','catalog','transition','ending','header_footer')}
        pages = TemplateSuiteService.__new__(TemplateSuiteService).build_pptx_layout_html(suite)
        self.assertEqual(set(pages), {'cover','catalog','transition','content','ending'})
        soup = BeautifulSoup(pages['cover'], 'html.parser')
        self.assertEqual(soup.h1['data-pptx-slot'], 'cover_title')
        self.assertEqual(soup.h1.text, '标题')
        self.assertEqual(soup.div.text, 'FIXED BRAND')
        self.assertFalse(soup.div.has_attr('data-pptx-slot'))
        self.assertEqual(soup.p.text, '第1章')
        self.assertEqual(soup.p.select_one('[data-pptx-slot]').text, '1')
        self.assertIn('font:40px Georgia', soup.style.text)
        self.assertNotIn('data-pptx-slot', soup.style.text)
        self.assertIsNone(soup.select_one('[data-pptx-slot=comment_only]'))

    def test_content_slot_has_no_preview_body(self):
        html = '<style>.stage{height:400px}</style><main class="stage">{{page_content}}</main><footer>固定页脚</footer>'
        pages = TemplateSuiteService.__new__(TemplateSuiteService).build_pptx_layout_html({'header_footer':html})
        soup = BeautifulSoup(pages['content'], 'html.parser')
        self.assertEqual(soup.main['data-pptx-slot'], 'page_content')
        self.assertEqual(soup.footer.text, '固定页脚')
        self.assertNotIn('生成 PPT 时由 AI 填充', soup.text)

if __name__ == '__main__':
    unittest.main()
