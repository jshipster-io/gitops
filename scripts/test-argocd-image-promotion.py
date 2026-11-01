#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('promotion', ROOT/'scripts/promote-argocd-images.py')
promotion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promotion)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT/'argocd-ksops-values.yaml').read_text()
        self.argo = 'prodacr1234.azurecr.io/platform-argocd@sha256:' + 'a'*64
        self.ksops = 'prodacr1234.azurecr.io/platform-ksops@sha256:' + 'b'*64
        self.source = 'c'*40

    def test_idempotent_pin_only_update_preserves_comments(self):
        result = promotion.update(self.text, self.argo, self.ksops, self.source)
        self.assertEqual(result, promotion.update(result, self.argo, self.ksops, self.source))
        self.assertEqual([s for s in self.text.splitlines() if s.lstrip().startswith('#')],
                         [s for s in result.splitlines() if s.lstrip().startswith('#')])

    def test_wrong_repository_mutable_and_swapped_receipts_rejected(self):
        for candidate in ['quay.io/argoproj/argocd@sha256:'+'a'*64, self.ksops,
                          'prodacr1234.azurecr.io/platform-argocd:latest', self.argo+'\nextra']:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                promotion.update(self.text, candidate, self.ksops, self.source)

    def test_unknown_structure_rejected(self):
        with self.assertRaises(ValueError):
            promotion.update(self.text.replace('  image:\n', '  image: {}\nunused:\n'),
                             self.argo, self.ksops, self.source)


if __name__ == '__main__':
    unittest.main()
