import unittest

from calculator_core import CalculationError, calculate


class CalculatorTests(unittest.TestCase):
    def test_exact_decimal_and_operator_precedence(self):
        values = {
            '0.1+0.2': '0.3',
            '(2+3)×4': '20',
            '−2^2': '-4',
            '2^-3': '0.125',
            '2^3^2': '512',
            '20% * 15': '3',
            '3 ÷ .5': '6',
            '1e-8': '1e-8',
        }
        for expression, expected in values.items():
            with self.subTest(expression=expression):
                self.assertEqual(calculate(expression), expected)

    def test_rejects_code_and_limits_pathological_inputs(self):
        for expression in ("__import__('os')", '2 + float("inf")', '1/0', '0^-1',
                           '1e999999', '1e-2000/1e2000', '2^2001', '10^2^2000', '2'*257,
                           '('*100+'2'+')'*100, '(2+3', '2(3+4)'):
            with self.subTest(expression=expression), self.assertRaises(CalculationError):
                calculate(expression)

    def test_decimal_scientific_functions_and_invalid_domains(self):
        self.assertEqual(calculate('sqrt(9)^2 + abs(-0.1)'), '9.1')
        self.assertEqual(calculate('log10(1e12)+ln(1)'), '12')
        self.assertEqual(calculate('SQRT(abs(-16))'), '4')
        for expression in ('sqrt(-2)', 'ln(0)', 'log10(-1)', 'sqrt 9', 'sqrt()', 'sqrtish(9)'):
            with self.subTest(expression=expression), self.assertRaises(CalculationError):
                calculate(expression)
