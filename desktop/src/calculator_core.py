"""Bounded arithmetic for Calculator and launcher results. Never evaluates code."""
from decimal import Context, Decimal, DecimalException, Underflow, localcontext
import re

MAX_EXPRESSION = 256
MAX_TOKENS = 128
MAX_EXPONENT = 2000
_NUMBER = re.compile(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_FUNCTION = re.compile(r'(?:sqrt|abs|ln|log10)(?![a-z0-9_])', re.IGNORECASE)
_NORMALIZE = str.maketrans({'−':'-', '×':'*', '·':'*', '÷':'/', '％':'%'})
_PRECEDENCE = {'+': 10, '-': 10, '*': 20, '/': 20, '^': 40}


class CalculationError(ValueError):
    """An expression cannot be safely parsed or calculated."""


def _tokenize(expression):
    tokens = []
    cursor = 0
    while cursor < len(expression):
        ch = expression[cursor]
        if ch.isspace():
            cursor += 1
            continue
        number = _NUMBER.match(expression, cursor)
        if number:
            raw = number[0]
            if 'e' in raw.lower() and abs(int(raw.lower().split('e')[1])) > MAX_EXPONENT:
                raise CalculationError('Exponent is too large')
            tokens.append(Decimal(raw))
            cursor = number.end()
        elif expression.startswith('**', cursor):
            tokens.append('^')
            cursor += 2
        elif ch in '+-*/^()%':
            tokens.append(ch)
            cursor += 1
        else:
            function = _FUNCTION.match(expression, cursor)
            if not function:
                raise CalculationError('Use numbers, arithmetic symbols, or a supported function')
            tokens.append(function[0].lower())
            cursor = function.end()
        if len(tokens) > MAX_TOKENS:
            raise CalculationError('Expression is too long')
    tokens.append('')
    return iter(tokens)


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current = next(tokens)

    def take(self):
        token = self.current
        self.current = next(self.tokens, '')
        return token

    def expression(self, minimum=0):
        token = self.take()
        if isinstance(token, Decimal):
            result = +token
        elif token in ('+', '-'):
            result = self.expression(30)
            if token == '-':
                result = -result
        elif token == '(':
            result = self.expression()
            if self.take() != ')':
                raise CalculationError('Close the parentheses')
        elif token in ('sqrt', 'abs', 'ln', 'log10'):
            if self.take() != '(':
                raise CalculationError('Put the function argument in parentheses')
            value = self.expression()
            if self.take() != ')':
                raise CalculationError('Close the parentheses')
            if token == 'sqrt':
                if value < 0:
                    raise CalculationError('Square root needs zero or a positive number')
                result = value.sqrt()
            elif token == 'abs':
                result = value.copy_abs()
            else:
                if value <= 0:
                    raise CalculationError('Logarithm needs a positive number')
                result = value.ln() if token == 'ln' else value.log10()
        else:
            raise CalculationError('Expected a number')
        while True:
            operator = self.current
            if operator == '%' and minimum <= 50:
                self.take()
                result /= 100
                continue
            level = _PRECEDENCE.get(operator, -1)
            if level < minimum:
                return result
            self.take()
            right = self.expression(level if operator == '^' else level + 1)
            if operator == '+':
                result += right
            elif operator == '-':
                result -= right
            elif operator == '*':
                result *= right
            elif operator == '/':
                if not right:
                    raise CalculationError('Cannot divide by zero')
                result /= right
            else:
                if right != right.to_integral_value() or abs(right) > MAX_EXPONENT:
                    raise CalculationError('Use a whole number as the exponent, from −2000 to 2000')
                if not result and right < 0:
                    raise CalculationError('Cannot divide by zero')
                result **= int(right)


def calculate(expression):
    """Return a repeatable, copyable decimal result for an arithmetic expression."""
    if not isinstance(expression, str) or len(expression) > MAX_EXPRESSION:
        raise CalculationError('Expression is too long')
    try:
        with localcontext(Context(prec=28, Emax=MAX_EXPONENT, Emin=-MAX_EXPONENT)) as context:
            context.traps[Underflow] = True
            parser = _Parser(_tokenize(expression.translate(_NORMALIZE)))
            result = parser.expression()
            if parser.current:
                raise CalculationError('Expected an arithmetic operator')
            if not result:
                return '0'
            result = result.normalize()
            return format(result, 'f' if -7 <= result.adjusted() <= 20 else 'e')
    except DecimalException as error:
        raise CalculationError('Result is outside the supported range') from error
