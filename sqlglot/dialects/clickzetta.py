from __future__ import annotations

import logging
import typing as t

from sqlglot import exp
from sqlglot import transforms
from sqlglot.dialects.dialect import (
    rename_func,
    if_sql,
)
from sqlglot.dialects.spark import Spark
from sqlglot.tokens import Tokenizer, TokenType

logger = logging.getLogger("sqlglot")

try:
    from sqlglot import local_clickzetta_settings
except ImportError as e:
    logger.warning(f"Failed to import local_clickzetta_settings, reason: {e}")


def _anonymous_agg_func(self: ClickZetta.Generator, expression: exp.AnonymousAggFunc) -> str:
    if expression.this.upper() == "UNIQEXACT":
        return self.sql(exp.Count(this=exp.Distinct(expressions=expression)))
    return self.func(expression.this, *expression.expressions)


def _transform_create(expression: exp.Expression) -> exp.Expression:
    """Remove index column constraints.
    Remove unique column constraint (due to not buggy input)."""
    schema = expression.this
    if isinstance(expression, exp.Create) and isinstance(schema, exp.Schema):
        to_remove = []
        for e in schema.expressions:
            if isinstance(e, exp.IndexColumnConstraint) or isinstance(
                e, exp.UniqueColumnConstraint
            ):
                to_remove.append(e)
        for e in to_remove:
            schema.expressions.remove(e)
    return expression


def _groupconcat_to_wmconcat(self: ClickZetta.Generator, expression: exp.GroupConcat) -> str:
    this = self.sql(expression, "this")
    sep = expression.args.get("separator")
    if not sep:
        sep = exp.Literal.string(",")
    return f"WM_CONCAT({sep}, {self.sql(this)})"


def _anonymous_func(self: ClickZetta.Generator, expression: exp.Anonymous) -> str:
    dialect = self.sql(expression.parent_select, "dialect")
    upper_name = expression.this.upper()
    if upper_name == "GETDATE":
        return "CURRENT_TIMESTAMP()"
    elif upper_name == "LAST_DAY_OF_MONTH":
        return f"LAST_DAY({self.sql(expression.expressions[0])})"
    elif upper_name == "TO_ISO8601":
        return f"DATE_FORMAT({self.sql(expression.expressions[0])}, 'yyyy-MM-dd\\'T\\'hh:mm:ss.SSSxxx')"
    elif upper_name == "MAP_AGG":
        return f"MAP_FROM_ENTRIES(COLLECT_LIST(STRUCT({self.expressions(expression)})))"
    elif upper_name == "JSON_ARRAY_GET":
        if len(expression.expressions) != 2:
            raise ValueError(f"JSON_ARRAY_GET needs 2 args, got {len(expression.expressions)}")
        arg1 = self.sql(expression.expressions[0])
        arg2 = self.sql(expression.expressions[1])
        return f"IF(TYPEOF({arg1}) == 'json', ({arg1}::JSON)[{arg2}], PARSE_JSON({arg1}::STRING)[{arg2}])"
    elif upper_name == "PARSE_DATETIME":
        return f"TO_TIMESTAMP({self.sql(expression.expressions[0])}, {self.sql(expression.expressions[1])})"
    elif upper_name == "FROM_ISO8601_TIMESTAMP":
        return f"CAST({self.sql(expression.expressions[0])} AS TIMESTAMP)"
    elif upper_name == "DOW":
        # dow in presto is an alias of day_of_week, which is equivalent to dayofweek_iso
        # https://prestodb.io/docs/current/functions/datetime.html#day_of_week-x-bigint
        # https://doc.clickzetta.com/en-US/sql_functions/scalar_functions/datetime_functions/dayofweek_iso
        return f"DAYOFWEEK_ISO({self.sql(expression.expressions[0])})"
    elif upper_name == "DOY":
        return f"DAYOFYEAR({self.sql(expression.expressions[0])})"
    elif upper_name == "YOW" or upper_name == "YEAR_OF_WEEK":
        return f"YEAROFWEEK({self.sql(expression.expressions[0])})"
    elif upper_name == "GROUPING":
        return f"GROUPING_ID({self.expressions(expression, flat=True)})"
    elif upper_name == "MURMUR_HASH3_32":
        return f"MURMURHASH3_32({self.sql(expression.expressions[0])})"
    elif upper_name == "GET_JSON_OBJECT":
        return _build_parse_json_sql(
            upper_name, self, expression.expressions[0], expression.expressions[1], dialect=dialect
        )
    elif (
        "VISITPARAMEXTRACT" in upper_name
        or "JSONEXTRACT" in upper_name
        or "SIMPLEJSONEXTRACT" in upper_name
    ):
        # VISITPARAMEXTRACT is alias of SIMPLEJSONEXTRACT in ClickHouse
        # The JSONEXTRACT parameters indices_or_keys currently not supported
        # https://clickhouse.com/docs/en/sql-reference/functions/json-functions#simplejsonextractfloat
        upper_name_subfix = upper_name.replace("VISITPARAMEXTRACT", "").replace("JSONEXTRACT", "")
        func_name = "JSON_EXTRACT"
        if upper_name_subfix == "BOOL":
            func_name = "JSON_EXTRACT_BOOLEAN"
        elif upper_name_subfix == "INT":
            func_name = "JSON_EXTRACT_BIGINT"
        elif upper_name_subfix == "FLOAT":
            func_name = "JSON_EXTRACT_DOUBLE"
        elif upper_name_subfix == "STRING":
            func_name = "JSON_EXTRACT_STRING"
        exprs = expression.expressions
        extract_sql = _build_parse_json_sql(func_name, self, exprs[0], exprs[1], dialect=dialect)
        if upper_name_subfix == "ARRAYRAW":
            extract_sql = f"{extract_sql}::ARRAY<JSON>"
        return extract_sql
    elif upper_name == "REPLACEALL":
        return self.func(
            "REPLACE",
            expression.expressions[0],
            expression.expressions[1],
            expression.expressions[2],
        )
    elif upper_name == "TOSTARTOFDAY":
        return f"DATE_TRUNC('DAY', {self.sql(expression.expressions[0])})"
    elif upper_name == "TOSTARTOFHOUR":
        return f"DATE_TRUNC('HOUR', {self.sql(expression.expressions[0])})"
    elif upper_name == "TOSTARTOFMINUTE":
        return f"DATE_TRUNC('MINUTE', {self.sql(expression.expressions[0])})"
    elif upper_name == "TOSTARTOFMONTH":
        return f"DATE_TRUNC('MONTH', {self.sql(expression.expressions[0])})"
    elif upper_name == "TOSTARTOFQUARTER":
        return f"DATE_TRUNC('QUARTER', {self.sql(expression.expressions[0])})"
    elif upper_name == "TOSTARTOFSECOND":
        return f"DATE_TRUNC('SECOND', {self.sql(expression.expressions[0])})"
    elif upper_name == "TOSTARTOFWEEK":
        return f"DATE_TRUNC('WEEK', {self.sql(expression.expressions[0])})"
    elif upper_name == "TOSTARTOFYEAR":
        return f"DATE_TRUNC('YEAR', {self.sql(expression.expressions[0])})"
    # return as it is
    return self.func(expression.this, *expression.expressions)


def nullif_to_if(self: ClickZetta.Generator, expression: exp.Nullif):
    cond = exp.EQ(this=expression.this, expression=expression.expression)
    ret = exp.If(this=cond, true=exp.Null(), false=expression.this)
    return self.sql(ret)


def unnest_to_explode(
    expression: exp.Expression,
    unnest_using_arrays_zip: bool = True,
    generator: t.Optional[ClickZetta.Generator] = None,
) -> exp.Expression:
    """Convert cross join unnest into lateral view explode."""

    def _unnest_zip_exprs(
        u: exp.Unnest, unnest_exprs: t.List[exp.Expression], has_multi_expr: bool
    ) -> t.List[exp.Expression]:
        if has_multi_expr:
            if not unnest_using_arrays_zip:
                if generator:
                    generator.unsupported(
                        f"Multiple expressions in UNNEST are not supported in "
                        f"{generator.dialect.__module__.split('.')[-1].upper()}"
                    )
            else:
                # Use INLINE(ARRAYS_ZIP(...)) for multiple expressions
                zip_exprs: t.List[exp.Expression] = [
                    exp.Anonymous(this="ARRAYS_ZIP", expressions=unnest_exprs)
                ]
                u.set("expressions", zip_exprs)
                return zip_exprs
        return unnest_exprs

    def _udtf_type(u: exp.Unnest, has_multi_expr: bool) -> t.Type[exp.Func]:
        if u.args.get("offset"):
            return exp.Posexplode
        return exp.Inline if has_multi_expr else exp.Explode

    if isinstance(expression, exp.Select):
        for join in expression.args.get("joins") or []:
            join_expr = join.this

            is_lateral = isinstance(join_expr, exp.Lateral)

            unnest = join_expr.this if is_lateral else join_expr

            if isinstance(unnest, exp.Unnest):
                if is_lateral:
                    alias = join_expr.args.get("alias")
                else:
                    alias = unnest.args.get("alias")
                exprs = unnest.expressions
                # The number of unnest.expressions will be changed by _unnest_zip_exprs, we need to record it here
                has_multi_expr = len(exprs) > 1
                exprs = _unnest_zip_exprs(unnest, exprs, has_multi_expr)

                expression.args["joins"].remove(join)

                alias_cols = alias.columns if alias else []
                for e, column in zip(exprs, alias_cols):
                    expression.append(
                        "laterals",
                        exp.Lateral(
                            this=_udtf_type(unnest, has_multi_expr)(this=e),
                            view=True,
                            alias=exp.TableAlias(
                                this=alias.this,  # type: ignore
                                columns=alias_cols if unnest_using_arrays_zip else [column],  # type: ignore
                            ),
                        ),
                    )

    return expression


def unnest_to_values(self: ClickZetta.Generator, expression: exp.Unnest):
    # If the array contains only tuples, the array is treated as a single map column.
    # https://prestodb.io/docs/current/sql/select.html#unnest
    exprs = expression.expressions
    if (
        isinstance(exprs, list)
        and len(exprs) == 1
        and isinstance(exprs[0], exp.Array)
        and all(isinstance(e, exp.Tuple) for e in exprs[0].expressions)
    ):
        array = exprs[0].expressions
        alias = expression.args.get("alias")
        ret = exp.Values(expressions=array, alias=alias)
        return self.sql(ret)
    elif len(expression.expressions) == 1:
        ret = f"EXPLODE({self.sql(expression.expressions[0])})"
        alias = expression.args.get("alias")
        if alias:
            ret = f"{ret} AS {self.tablealias_sql(expression.args.get('alias'))}"
        return ret
    # Not set dialect, will call unnest_sql in generator.Generator to ensure that it will not be affected
    # by upstream changes
    return expression.sql()


def date_add_sql(self: ClickZetta.Generator, expression: exp.DateAdd) -> str:
    """
    Convert date_add to TIMESTAMP_OR_DATE_ADD.

    Note the currently difference between `exp.DateAdd` and `exp.TimestampAdd` and `exp.Anonymous(date_add)`
    | dialect | sql example | expression | return type |
    |---------|--------------|------------|--------------|
    | starrocks | select date_add('2010-11-30 23:59:59', INTERVAL 2 DAY) | exp.DateAdd | timestamp or date |
    | presto | select date_add('2010-11-30 23:59:59', INTERVAL 2 DAY) | exp.DateAdd | timestamp or date |
    | spark | select date_add('2024-01-01', 1) | exp.Anonymous | date |
    | spark | select dateadd(DAY, 1, '2024-01-01') | exp.TimestampAdd | timestamp |
    """
    # https://prestodb.io/docs/current/functions/datetime.html#date_add
    unit = expression.args.get("unit")
    if not unit:
        unit = exp.Literal.string("DAY")
    if isinstance(unit, exp.Var):
        unit_str = f"'{self.sql(unit)}'"
    else:
        unit_str = self.sql(unit)
    # canonicalize INTERVAL values to number literals
    interval = expression.expression
    if interval and interval.is_string:
        interval = exp.Literal.number(interval.this)
    return f"TIMESTAMP_OR_DATE_ADD({unit_str}, {self.sql(interval)}, {self.sql(expression.this)})"


def _transform_group_sql(expression: exp.Expression) -> exp.Expression:
    # Handle CUBE
    cube = expression.args.get("cube", [])
    group_exprs = expression.expressions
    # If the cube list is only "true" not Column expressions, then convert to Column expressions
    if cube and isinstance(cube[0], exp.Cube):
        exprs = cube[0].expressions
        if not exprs:
            cube[0].set("expressions", group_exprs)
            return exp.Group(cube=cube, expressions=[])

    # Handle ROLLUP
    rollup = expression.args.get("rollup", [])
    if rollup and isinstance(rollup[0], exp.Rollup):
        exprs = rollup[0].expressions
        if not exprs:
            rollup[0].set("expressions", group_exprs)
            return exp.Group(cube=rollup, expressions=[])

    # Handle GROUPING SETS
    grouping = expression.args.get("grouping_sets", [])
    if grouping and isinstance(grouping[0], exp.GroupingSets):
        return exp.Group(grouping_sets=grouping, expressions=[])

    # If no special clauses, return the original expression
    return expression


def _json_extract(
    name: str, self: ClickZetta.Generator, expression: exp.JSONExtract | exp.JSONExtractScalar
) -> str:
    return _build_parse_json_sql(
        name, self, expression.this, expression.expression, expression.expressions
    )


def _build_parse_json_sql(
    name: str,
    self: ClickZetta.Generator,
    json: exp.Expression,
    path: exp.Expression,
    exprs: t.List[exp.Expression] = (),
    dialect: str = "",
) -> str:
    if not dialect:
        dialect = self.sql(path.parent_select, "dialect")
    # If it is not a Literal type but a JsonPath, the $ prefix will be automatically added during translation
    if isinstance(path, exp.Literal) and isinstance(path.this, str):
        path_str = path.this
        # The key in Clickhouse's jsonpath contains a dot, not a hierarchical relationship, but a part of the key.
        # Other dialects do not need special processing
        if path_str.find(".") != -1 and dialect == "CLICKHOUSE":
            path_str = rf"'$[\'{path_str}\']'"
        # If the literal starts with $., use JSON_EXTRACT directly
        elif path_str.startswith("$."):
            path_str = f"'{path_str}'"
        else:
            path_str = f"'$.{path_str}'"
    else:
        # If it is not a Literal type but a JsonPath, the $ prefix will be automatically added during translation
        path_str = self.sql(path)

    if name.upper() != "GET_JSON_OBJECT" and isinstance(json, exp.Literal) and json.is_string:
        return self.func(name, exp.ParseJSON(this=json), path_str, *exprs)
    return self.func(name, json, path_str, *exprs)


def _parse_json(self, e: exp.ParseJSON) -> str:
    if isinstance(e.this, exp.Literal) and e.this.is_string:
        return f"JSON '{e.this.this}'"
    return self.func("PARSE_JSON", e.this)


class ClickZetta(Spark):
    NULL_ORDERING = "nulls_are_small"
    LOG_BASE_FIRST = None
    # https://github.com/tobymao/sqlglot/issues/4013
    STRICT_JSON_PATH_SYNTAX = False

    class Tokenizer(Spark.Tokenizer):
        KEYWORDS = {
            **Tokenizer.KEYWORDS,
            "CREATE USER": TokenType.COMMAND,
            "DROP USER": TokenType.COMMAND,
            "SHOW USER": TokenType.COMMAND,
            "REVOKE": TokenType.COMMAND,
        }

    class Parser(Spark.Parser):
        PROPERTY_PARSERS = {
            **Spark.Parser.PROPERTY_PARSERS,
            # ClickZetta has properties syntax similar to MySQL. e.g. PROPERTIES('key1'='value')
            "PROPERTIES": lambda self: self._parse_wrapped_properties(),
        }

        def _to_prop_eq(self, expression: exp.Expression, index: int) -> exp.Expression:
            # ClickZetta does not support add alias for STRUCT function, so we need to directly return the expression
            # Otherwise, if is useful, we can use to `named_struct` in the future
            return expression

    class Generator(Spark.Generator):
        RESERVED_KEYWORDS = {
            "all",
            "user",
            "to",
            "check",
            "order",
            "current_timestamp",
            "current_date",
        }
        WITH_PROPERTIES_PREFIX = "PROPERTIES"

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
            # starrocks decimal types
            exp.DataType.Type.DECIMAL32: "DECIMAL",
            exp.DataType.Type.DECIMAL64: "DECIMAL",
            exp.DataType.Type.DECIMAL128: "DECIMAL",
        }

        PROPERTIES_LOCATION = {
            **Spark.Generator.PROPERTIES_LOCATION,
            exp.PrimaryKey: exp.Properties.Location.POST_NAME,
            exp.EngineProperty: exp.Properties.Location.POST_SCHEMA,
        }

        TRANSFORMS = {
            **Spark.Generator.TRANSFORMS,
            exp.Select: transforms.preprocess(
                [
                    transforms.eliminate_qualify,
                    transforms.eliminate_distinct_on,
                    unnest_to_explode,
                ]
            ),
            exp.Anonymous: _anonymous_func,
            exp.AnonymousAggFunc: _anonymous_agg_func,
            exp.CastToStrType: lambda self, e: "CAST({} AS {})".format(
                self.sql(e, "this"), self.sql(e, "to").strip("'").upper()
            ),
            # in MaxCompute, datetime(col) is an alias of cast(col as datetime)
            exp.Datetime: rename_func("TO_TIMESTAMP"),
            exp.DefaultColumnConstraint: lambda self, e: "",
            exp.DuplicateKeyProperty: lambda self, e: "",
            exp.OnUpdateColumnConstraint: lambda self, e: "",
            exp.AutoIncrementColumnConstraint: lambda self, e: "",
            exp.CollateColumnConstraint: lambda self, e: "",
            exp.CharacterSetColumnConstraint: lambda self, e: "",
            exp.Create: transforms.preprocess([_transform_create]),
            exp.GroupConcat: _groupconcat_to_wmconcat,
            exp.CurrentTime: lambda self, e: "DATE_FORMAT(NOW(),'HH:mm:ss')",
            exp.AtTimeZone: lambda self, e: self.func(
                "CONVERT_TIMEZONE", e.args.get("zone"), e.this
            ),
            exp.EngineProperty: lambda self, e: "",
            exp.Pow: rename_func("POW"),
            exp.ApproxQuantile: rename_func("APPROX_PERCENTILE"),
            exp.JSONFormat: rename_func("TO_JSON"),
            exp.ParseJSON: _parse_json,
            exp.Nullif: nullif_to_if,
            exp.If: if_sql(false_value=exp.Null()),
            exp.Unnest: unnest_to_values,
            exp.Try: lambda self, e: self.sql(e, "this"),
            exp.GenerateSeries: rename_func("SEQUENCE"),
            exp.DateAdd: date_add_sql,
            exp.DayOfWeekIso: lambda self, e: self.func("DAYOFWEEK_ISO", e.this),
            exp.Group: transforms.preprocess([_transform_group_sql]),
            exp.RegexpLike: rename_func("RLIKE"),
            exp.JSONExtract: lambda self, e: _json_extract("JSON_EXTRACT", self, e),
            exp.JSONExtractScalar: lambda self, e: _json_extract("JSON_EXTRACT", self, e),
            exp.Chr: lambda self, e: self.func(
                "CHAR", exp.cast(self.sql(*e.expressions), exp.DataType.Type.INT)
            ),
            exp.ArrayAgg: rename_func("COLLECT_LIST"),
            exp.FromISO8601Timestamp: lambda self,
            e: f"{self.sql(exp.cast(e.this, exp.DataType.Type.TIMESTAMP))}",
        }

        def datatype_sql(self, expression: exp.DataType) -> str:
            """Remove unsupported type params from int types: eg. int(10) -> int
            Remove type param from enum series since it will be mapped as STRING."""
            type_value = expression.this
            type_sql = (
                self.TYPE_MAPPING.get(type_value, type_value.value)
                if isinstance(type_value, exp.DataType.Type)
                else type_value
            )
            if type_value in exp.DataType.INTEGER_TYPES or type_value in {
                exp.DataType.Type.UTINYINT,
                exp.DataType.Type.USMALLINT,
                exp.DataType.Type.UMEDIUMINT,
                exp.DataType.Type.UINT,
                exp.DataType.Type.UINT128,
                exp.DataType.Type.UINT256,
                exp.DataType.Type.ENUM,
                exp.DataType.Type.FLOAT,
                exp.DataType.Type.DOUBLE,
            }:
                return type_sql
            return super().datatype_sql(expression)

        def distributedbyproperty_sql(self, expression: exp.DistributedByProperty) -> str:
            expressions = self.expressions(expression, key="expressions", flat=True)
            order = self.expressions(expression, key="order", flat=True)
            order = f" SORTED BY {order}" if order else ""
            buckets = self.sql(expression, "buckets")
            if not buckets:
                self.unsupported(
                    "DistributedByHash without buckets, clickzetta requires a number of buckets"
                )
            return f"CLUSTERED BY ({expressions}){order} INTO {buckets} BUCKETS"

        def preprocess(self, expression: exp.Expression) -> exp.Expression:
            """Apply generic preprocessing transformations to a given expression."""

            # do not move ctes to top levels

            if self.ENSURE_BOOLS:
                from sqlglot.transforms import ensure_bools

                expression = ensure_bools(expression)

            return expression
