from __future__ import annotations
import typing as t

from collections import defaultdict
from sqlglot import exp, transforms
from sqlglot.dialects.spark import Spark
from sqlglot.expressions import Div
from sqlglot.tokens import Tokenizer, TokenType
from sqlglot.dialects.dialect import (
    rename_func,
    if_sql,
)

def _transform_create(expression: exp.Expression) -> exp.Expression:
    """Remove index column constraints.
    Remove unique column constraint (due to not buggy input)."""
    schema = expression.this
    if isinstance(expression, exp.Create) and isinstance(schema, exp.Schema):
        to_remove = []
        for e in schema.expressions:
            if isinstance(e, exp.IndexColumnConstraint) or \
                    isinstance(e, exp.UniqueColumnConstraint):
                to_remove.append(e)
        for e in to_remove:
            schema.expressions.remove(e)
    return expression


def _groupconcat_to_wmconcat(self: ClickZetta.Generator, expression: exp.GroupConcat) -> str:
    this = self.sql(expression, "this")
    sep = expression.args.get('separator')
    if not sep:
        sep = exp.Literal.string(',')
    return f"WM_CONCAT({sep}, {self.sql(this)})"


def _anonymous_func(self: ClickZetta.Generator, expression: exp.Anonymous) -> str:
    if expression.this.upper() == 'DATETIME':
        # in MaxCompute, datetime(col) is an alias of cast(col as datetime)
        return f"{self.sql(expression.expressions[0])}::TIMESTAMP"
    elif expression.this.upper() == 'GETDATE':
        return f"CURRENT_TIMESTAMP()"
    elif expression.this.upper() == 'TRY':
        return self.sql(expression.expressions[0])

    # return as it is
    args = ", ".join(self.sql(e) for e in expression.expressions)
    return f"{expression.this}({args})"

def nullif_to_if(self: ClickZetta.Generator, expression: exp.Nullif):
    cond = exp.EQ(this=expression.this, expression=expression.expression)
    ret = exp.If(this=cond, true=exp.Null(), false=expression.this)
    return self.sql(ret)

def unnest_to_values(self: ClickZetta.Generator, expression: exp.Unnest):
    array = expression.expressions[0].expressions # TODO: could be dangerous?
    alias = expression.args.get('alias')
    ret = exp.Values(expressions=array, alias=alias)
    return self.sql(ret)

class ClickZetta(Spark):
    NULL_ORDERING = "nulls_are_small"

    class Tokenizer(Spark.Tokenizer):
        KEYWORDS = {
            **Tokenizer.KEYWORDS,
            "CREATE USER": TokenType.COMMAND,
            "DROP USER": TokenType.COMMAND,
            "SHOW USER": TokenType.COMMAND,
            "REVOKE": TokenType.COMMAND,
        }

    class Parser(Spark.Parser):
        pass

    class Generator(Spark.Generator):

        TYPE_MAPPING = {
            **Spark.Generator.TYPE_MAPPING,
            exp.DataType.Type.MEDIUMTEXT: "STRING",
            exp.DataType.Type.LONGTEXT: "STRING",
            exp.DataType.Type.VARIANT: "STRING",
            exp.DataType.Type.ENUM: "STRING",
            exp.DataType.Type.ENUM16: "STRING",
            exp.DataType.Type.ENUM8: "STRING",
            # mysql unsigned types
            exp.DataType.Type.UINT: "INT",
            exp.DataType.Type.UTINYINT: "TINYINT",
            exp.DataType.Type.USMALLINT: "SMALLINT",
            exp.DataType.Type.UMEDIUMINT: "INT",
            exp.DataType.Type.UBIGINT: "BIGINT",
            exp.DataType.Type.UDECIMAL: "DECIMAL",
            # postgres serial types
            exp.DataType.Type.BIGSERIAL: "BIGINT",
            exp.DataType.Type.SERIAL: "INT",
            exp.DataType.Type.SMALLSERIAL: "SMALLINT",
            exp.DataType.Type.BIGDECIMAL: "DECIMAL",
        }

        PROPERTIES_LOCATION = {
            **Spark.Generator.PROPERTIES_LOCATION,
            exp.DistributedByProperty: exp.Properties.Location.POST_SCHEMA,
            exp.PrimaryKey: exp.Properties.Location.POST_NAME,
            exp.EngineProperty: exp.Properties.Location.POST_SCHEMA,
        }

        TRANSFORMS = {
            **Spark.Generator.TRANSFORMS,
            exp.DefaultColumnConstraint: lambda self, e: '',
            exp.OnUpdateColumnConstraint: lambda self, e: '',
            exp.AutoIncrementColumnConstraint: lambda self, e: '',
            exp.CollateColumnConstraint: lambda self, e: '',
            exp.CharacterSetColumnConstraint: lambda self, e: '',
            exp.Create: transforms.preprocess([_transform_create]),
            exp.GroupConcat: _groupconcat_to_wmconcat,
            exp.AesDecrypt: rename_func("AES_DECRYPT_MYSQL"),
            exp.CurrentTime: lambda self, e: "DATE_FORMAT(NOW(),'HH:mm:ss')",
            exp.Anonymous: _anonymous_func,
            exp.AtTimeZone: lambda self, e: self.func(
                "CONVERT_TIMEZONE", e.args.get("zone"), self._cz_integer_div_sql(e.this.args.get("this"))
            ),
            exp.UnixToTime: lambda self, e: self.func(
                "CONVERT_TIMEZONE", "'UTC+0'", self._cz_integer_div_sql(e.this)
            ),
            exp.DistributedByProperty: lambda self, e: self.distributedbyproperty_sql(e),
            exp.EngineProperty: lambda self, e: '',
            exp.TimeToStr: lambda self, e: self.func(
                "DATE_FORMAT_PG", e.this, str(e.args.get("format")).replace("%m", "mm")
            ),
            exp.Pow: rename_func("POW"),
            exp.ApproxQuantile: rename_func("APPROX_PERCENTILE"),
            exp.JSONFormat: rename_func("TO_JSON"),
            exp.ParseJSON: lambda self, e: f"JSON {self.sql(e.this)}",
            exp.Nullif: nullif_to_if,
            exp.If: if_sql(false_value=exp.Null()),
            exp.Unnest: unnest_to_values,
        }

        def distributedbyproperty_sql(self, expression: exp.DistributedByProperty) -> str:
            expressions = self.expressions(expression, key="expressions", flat=True)
            sorted_by = self.expressions(expression, key="sorted_by", flat=True)
            sorted_by = f" SORTED BY ({sorted_by})" if sorted_by else ""
            buckets = self.sql(expression, "buckets")
            return f"HASH CLUSTERED BY ({expressions}){sorted_by} INTO {buckets} BUCKETS"

        def datatype_sql(self, expression: exp.DataType) -> str:
            """Remove unsupported type params from int types: eg. int(10) -> int
            Remove type param from enum series since it will be mapped as STRING."""
            type_value = expression.this
            type_sql = (
                self.TYPE_MAPPING.get(type_value, type_value.value)
                if isinstance(type_value, exp.DataType.Type)
                else type_value
            )
            if type_value in exp.DataType.INTEGER_TYPES or \
                type_value in {
                    exp.DataType.Type.UTINYINT,
                    exp.DataType.Type.USMALLINT,
                    exp.DataType.Type.UMEDIUMINT,
                    exp.DataType.Type.UINT,
                    exp.DataType.Type.UINT128,
                    exp.DataType.Type.UINT256,

                    exp.DataType.Type.ENUM,
               }:
                return type_sql
            return super().datatype_sql(expression)

        def tochar_sql(self, expression: exp.ToChar) -> str:
            this = expression.args.get('this')
            format = expression.args.get('format')
            if format:
                format_str = str(format).replace('mm', 'MM').replace('mi', 'mm')
                return f"DATE_FORMAT_PG({self.sql(this)}, {self.sql(format_str)})"

            return super().tochar_sql(expression)

        def _cz_integer_div_sql(self, expression: exp.Div) -> Div | str:
            if not isinstance(expression, exp.Div):
                return expression
            l, r = expression.left, expression.right

            if not self.SAFE_DIVISION and expression.args.get("safe"):
                r.replace(exp.Nullif(this=r.copy(), expression=exp.Literal.number(0)))

            if self.TYPED_DIVISION and not expression.args.get("typed"):
                if not l.is_type(*exp.DataType.FLOAT_TYPES) and not r.is_type(
                        *exp.DataType.FLOAT_TYPES
                ):
                    l.replace(exp.cast(l.copy(), to=exp.DataType.Type.DOUBLE))

            elif not self.TYPED_DIVISION and expression.args.get("typed"):
                if l.is_type(*exp.DataType.INTEGER_TYPES) and r.is_type(*exp.DataType.INTEGER_TYPES):
                    return self.sql(
                        exp.cast(
                            l / r,
                            to=exp.DataType.Type.BIGINT,
                        )
                    )
            return self.binary(expression, "DIV")

        def maybe_comment(self, sql: str, expression: exp.Expression | None = None,
                          comments: List[str] | None = None) -> str:
            comments = (
                ((expression and expression.comments) if comments is None else comments)  # type: ignore
                if self.comments
                else None
            )

            if not comments or isinstance(expression, self.EXCLUDE_COMMENTS):
                return sql

            comments_sql = "\n".join(
                f"/* {self.pad_comment(comment)} */" for comment in comments if comment
            )

            if not comments_sql:
                return sql

            if isinstance(expression, self.WITH_SEPARATED_COMMENTS):
                return (
                    f"{self.sep()}{comments_sql}{sql}"
                    if sql[0].isspace()
                    else f"{comments_sql}{self.sep()}{sql}"
                )

            return f"{sql} {comments_sql}"

        def create_sql(self, expression: exp.Create) -> str:
            kind = self.sql(expression, "kind").upper()
            properties = expression.args.get("properties")
            properties_locs = self.locate_properties(properties) if properties else defaultdict()
            this = self.createable_sql(expression, properties_locs)

            properties_sql = ""
            if properties_locs.get(exp.Properties.Location.POST_SCHEMA) or properties_locs.get(
                    exp.Properties.Location.POST_WITH
            ):
                properties_sql = self.sql(
                    exp.Properties(
                        expressions=[
                            *properties_locs[exp.Properties.Location.POST_SCHEMA],
                            *properties_locs[exp.Properties.Location.POST_WITH],
                        ]
                    )
                )
            # print("properties_locs:", properties_locs)
            primarykey_sql = ""
            if expression.args.get("kind") == "TABLE":
                if properties_locs.get(exp.Properties.Location.POST_NAME):
                    exp_list = properties_locs.get(exp.Properties.Location.POST_NAME)
                    for express in exp_list:
                        if express.key == "primarykey":
                            primarykey_sql = self.sql(express)

            begin = " BEGIN" if expression.args.get("begin") else ""
            end = " END" if expression.args.get("end") else ""

            expression_sql = self.sql(expression, "expression")
            if expression_sql:
                expression_sql = f"{begin}{self.sep()}{expression_sql}{end}"

                if self.CREATE_FUNCTION_RETURN_AS or not isinstance(expression.expression, exp.Return):
                    if properties_locs.get(exp.Properties.Location.POST_ALIAS):
                        postalias_props_sql = self.properties(
                            exp.Properties(
                                expressions=properties_locs[exp.Properties.Location.POST_ALIAS]
                            ),
                            wrapped=False,
                        )
                        expression_sql = f" AS {postalias_props_sql}{expression_sql}"
                    else:
                        expression_sql = f" AS{expression_sql}"

            postindex_props_sql = ""
            if properties_locs.get(exp.Properties.Location.POST_INDEX):
                postindex_props_sql = self.properties(
                    exp.Properties(expressions=properties_locs[exp.Properties.Location.POST_INDEX]),
                    wrapped=False,
                    prefix=" ",
                )

            indexes = self.expressions(expression, key="indexes", indent=False, sep=" ")
            indexes = f" {indexes}" if indexes else ""
            index_sql = indexes + postindex_props_sql

            replace = " OR REPLACE" if expression.args.get("replace") else ""
            unique = " UNIQUE" if expression.args.get("unique") else ""

            postcreate_props_sql = ""
            if properties_locs.get(exp.Properties.Location.POST_CREATE):
                postcreate_props_sql = self.properties(
                    exp.Properties(expressions=properties_locs[exp.Properties.Location.POST_CREATE]),
                    sep=" ",
                    prefix=" ",
                    wrapped=False,
                )

            modifiers = "".join((replace, unique, postcreate_props_sql))

            postexpression_props_sql = ""
            if properties_locs.get(exp.Properties.Location.POST_EXPRESSION):
                postexpression_props_sql = self.properties(
                    exp.Properties(
                        expressions=properties_locs[exp.Properties.Location.POST_EXPRESSION]
                    ),
                    sep=" ",
                    prefix=" ",
                    wrapped=False,
                )

            exists_sql = " IF NOT EXISTS" if expression.args.get("exists") else ""
            no_schema_binding = (
                " WITH NO SCHEMA BINDING" if expression.args.get("no_schema_binding") else ""
            )

            clone = self.sql(expression, "clone")
            clone = f" {clone}" if clone else ""

            if expression.args.get("kind") == "TABLE":
                if primarykey_sql == "":
                    expression_sql = f"CREATE{modifiers} {kind}{exists_sql} {this}{self.seg(')', sep='')}{properties_sql}{expression_sql}{postexpression_props_sql}{index_sql}{no_schema_binding}{clone}"
                else:
                    expression_sql = f"CREATE{modifiers} {kind}{exists_sql} {this} {primarykey_sql}{self.seg(')', sep='')}{properties_sql}{expression_sql}{postexpression_props_sql}{index_sql}{no_schema_binding}{clone}"
            else:
                expression_sql = f"CREATE{modifiers} {kind}{exists_sql} {this}{properties_sql}{expression_sql}{postexpression_props_sql}{index_sql}{no_schema_binding}{clone}"
            return self.prepend_ctes(expression, expression_sql)

        def schema_sql(self, expression: exp.Schema) -> str:
            this = self.sql(expression, "this")
            sql = self.schema_columns_sql(expression)
            return f"{this} {self.seg('(', sep='')}{sql}" if this and sql else this or sql

        def schema_columns_sql(self, expression: exp.Schema) -> str:
            if expression.expressions:
                sql = f"{self.expressions(expression)}"
                return sql
            return ""
