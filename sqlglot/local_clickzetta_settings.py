from sqlglot import exp
from sqlglot.helper import seq_get
from sqlglot.parser import Parser
from sqlglot.dialects.presto import Presto
from sqlglot.dialects.trino import Trino
from sqlglot.dialects.athena import Athena
from sqlglot.dialects.starrocks import StarRocks
from sqlglot.dialects.doris import Doris
from sqlglot.dialects.mysql import MySQL
from sqlglot.dialects.postgres import Postgres
from sqlglot.dialects.redshift import Redshift
from sqlglot.dialects.clickhouse import ClickHouse

# Note: This workaround only allows the syntax that has been adapted to the Source Dialect of Clickzetta to be hacked.
# Anything that can be solved through expression will not be allowed here.
for dialect in [MySQL, Presto, Trino, Athena, StarRocks, Doris]:
    dialect.Parser.FUNCTIONS["DATE_FORMAT"] = lambda args: exp.Anonymous(
        this="DATE_FORMAT_MYSQL", expressions=args
    )
    dialect.Parser.FUNCTIONS["AES_DECRYPT"] = lambda args: exp.Anonymous(
        this="AES_DECRYPT_MYSQL", expressions=args
    )
    dialect.Parser.FUNCTIONS["AES_ENCRYPT"] = lambda args: exp.Anonymous(
        this="AES_ENCRYPT_MYSQL", expressions=args
    )
ClickHouse.Parser.FUNCTIONS["FORMATDATETIME"] = lambda args: exp.Anonymous(
    this="DATE_FORMAT_MYSQL", expressions=args
)
for dialect in [Postgres, Redshift]:
    dialect.Parser.FUNCTIONS["TO_CHAR"] = lambda args: exp.Anonymous(
        this="DATE_FORMAT_PG", expressions=args
    )

# Add ClickHouse functions in a workaround way, delete after sqlglot supports it
ClickHouse.Parser.FUNCTIONS["FROMUNIXTIMESTAMP64MILLI"] = lambda args: exp.UnixToTime(
    this=seq_get(args, 0),
    zone=seq_get(args, 1) if len(args) == 2 else None,
    scale=exp.UnixToTime.MILLIS,
)
ClickHouse.Parser.FUNCTIONS["JSONEXTRACTSTRING"] = lambda args: exp.Anonymous(
    this="JSONEXTRACTSTRING", expressions=args
)
ClickHouse.Parser.FUNCTIONS["VISITPARAMEXTRACTSTRING"] = lambda args: exp.Anonymous(
    this="VISITPARAMEXTRACTSTRING", expressions=args
)
ClickHouse.Parser.FUNCTIONS["VISITPARAMEXTRACTRAW"] = lambda args: exp.Anonymous(
    this="GET_JSON_OBJECT", expressions=args
)
ClickHouse.Parser.FUNCTIONS["SIMPLEJSONEXTRACTRAW"] = lambda args: exp.Anonymous(
    this="GET_JSON_OBJECT", expressions=args
)
ClickHouse.Parser.FUNCTIONS["JSONEXTRACTRAW"] = lambda args: exp.Anonymous(
    this="GET_JSON_OBJECT", expressions=args
)
ClickHouse.Parser.FUNCTIONS["TODATETIME"] = lambda args: exp.cast(
    seq_get(args, 0), exp.DataType.Type.DATETIME
)
ClickHouse.Parser.FUNCTIONS["TODATE"] = lambda args: exp.cast(
    seq_get(args, 0), exp.DataType.Type.DATE
)

_parse_select = getattr(Parser, "_parse_select")


def preprocess_parse_select(self, *args, **kwargs):
    expression = _parse_select(self, *args, **kwargs)
    if not expression:
        return expression
    # source dialect
    read_dialect = self.dialect.__module__.split(".")[-1].upper()
    expression.set("dialect", read_dialect)
    if read_dialect == "PRESTO":
        _normalize_tuple_comparisons(expression)
    return expression


setattr(Parser, "_parse_select", preprocess_parse_select)


# According to #4042 suggestion, we create a custom transformation to handle presto tuple comparisons
# https://github.com/tobymao/sqlglot/issues/4042
def _normalize_tuple_comparisons(expression: exp.Expression):
    for tup in expression.find_all(exp.Tuple):
        if not isinstance(tup.parent, exp.Binary) or not isinstance(tup.parent, exp.Predicate):
            continue
        binary = tup.parent
        left, right = binary.this, binary.expression
        if not isinstance(left, exp.Tuple) or not isinstance(right, exp.Tuple):
            continue
        left_exprs = left.expressions
        right_exprs = right.expressions
        for i, (left_expr, right_expr) in enumerate(zip(left_exprs, right_exprs), start=1):
            alias = f"col{i}"
            if not isinstance(left_expr, exp.Alias):
                left_exprs[i - 1] = exp.Alias(this=left_expr, alias=exp.to_identifier(alias))
            else:
                left_exprs[i - 1].set("alias", exp.to_identifier(alias))

            if not isinstance(right_expr, exp.Alias):
                right_exprs[i - 1] = exp.Alias(this=right_expr, alias=exp.to_identifier(alias))
            else:
                right_exprs[i - 1].set("alias", exp.to_identifier(alias))
