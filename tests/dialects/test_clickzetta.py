from tests.dialects.test_dialect import Validator


class TestClickzetta(Validator):
    dialect = "clickzetta"

    def test_reserved_keyword(self):
        self.validate_all(
            "SELECT user.id from t as user",
            write={
                "clickzetta": "SELECT `user`.id FROM t AS `user`",
            },
        )
        self.validate_all(
            "with all as (select 1) select * from all",
            write={
                "clickzetta": "WITH `all` AS (SELECT 1) SELECT * FROM `all`",
            },
        )
        self.validate_all(
            "with check as (select 1) select * from check",
            write={
                "clickzetta": "WITH `check` AS (SELECT 1) SELECT * FROM `check`",
            },
        )
        self.validate_all(
            "select json_extract(to, '$.billing_zone') as to_billing_zone",
            write={
                "clickzetta": "SELECT JSON_EXTRACT(`to`, '$.billing_zone') AS to_billing_zone",
            },
        )

    def test_ddl_types(self):
        starrocks_ddl_sqls = [
            ("DISTRIBUTED BY HASH (col1) BUCKETS 1", "CLUSTERED BY (col1) INTO 1 BUCKETS"),
            (
                "DISTRIBUTED BY HASH (col1) BUCKETS 1 ORDER BY (col1)",
                "CLUSTERED BY (col1) SORTED BY (col1) INTO 1 BUCKETS",
            ),
            (
                "DISTRIBUTED BY HASH (col1) BUCKETS 1 PROPERTIES ('replication_num'='1')",
                "CLUSTERED BY (col1) INTO 1 BUCKETS PROPERTIES ('replication_num'='1')",
            ),
            (
                "DUPLICATE KEY (col1, col2) DISTRIBUTED BY HASH (col1) BUCKETS 1",
                "CLUSTERED BY (col1) INTO 1 BUCKETS",
            ),
            ("PARTITION BY (col1)", "PARTITIONED BY (col1)"),
        ]

        for prep in starrocks_ddl_sqls:
            with self.subTest(f"Testing create scheme: {prep}"):
                self.validate_all(
                    f"CREATE TABLE foo (col1 BIGINT, col2 BIGINT) {prep[1]}",
                    read={"starrocks": f"CREATE TABLE foo (col1 BIGINT, col2 BIGINT) {prep[0]}"},
                )

        # Test the different wider DECIMAL types
        self.validate_all(
            "CREATE TABLE foo (col0 DECIMAL(9, 1), col1 DECIMAL(9, 1), col2 DECIMAL(18, 10), col3 DECIMAL(38, 10)) CLUSTERED BY (col1) INTO 1 BUCKETS",
            read={
                "starrocks": "CREATE TABLE foo (col0 DECIMAL(9, 1), col1 DECIMAL32(9, 1), col2 DECIMAL64(18, 10), col3 DECIMAL128(38, 10)) DISTRIBUTED BY HASH (col1) BUCKETS 1"
            },
        )
        types = [
            ("SERIAL", "INT"),
            ("BIGSERIAL", "BIGINT"),
            ("ENUM", "STRING"),
            ("INT DEFAULT 0", "INT"),
        ]
        for type in types:
            with self.subTest(f"Testing covert postgres type: {type}"):
                self.validate_all(
                    f"CREATE TABLE foo (a {type[1]})",
                    read={
                        "postgres": f"CREATE TABLE foo (a {type[0]})",
                    },
                )

        # Test the mysql type
        types = [("DECIMAL UNSIGNED", "DECIMAL"), ("LONGTEXT", "STRING")]
        for type in types:
            with self.subTest(f"Testing covert mysql type: {type}"):
                self.validate_all(
                    f"CREATE TABLE foo (a {type[1]})",
                    read={
                        "mysql": f"CREATE TABLE foo (a {type[0]})",
                    },
                )

        # Test the starrocks type
        types = [
            ("INT(11)", "INT"),
            ("INT(11) NOT NULL", "INT NOT NULL"),
            ("SMALLINT(8)", "SMALLINT"),
            ("BIGINT(20)", "BIGINT"),
            ("datetime", "TIMESTAMP"),
            ("FLOAT(10, 2)", "FLOAT"),
            ("DOUBLE(10, 2)", "DOUBLE"),
            ("DECIMAL(10, 2)", "DECIMAL(10, 2)"),
            ("DECIMAL32(9, 1)", "DECIMAL(9, 1)"),
            ("DECIMAL64(18, 10)", "DECIMAL(18, 10)"),
            ("DECIMAL128(38, 10)", "DECIMAL(38, 10)"),
        ]
        for type in types:
            with self.subTest(f"Testing covert starrocks type: {type}"):
                self.validate_all(
                    f"CREATE TABLE foo (a {type[1]})",
                    read={
                        "starrocks": f"CREATE TABLE foo (a {type[0]})",
                    },
                )

        # Test create table with primary key, duplicate key, partitioned by, clustered by, sorted by and properties
        self.validate_all(
            "CREATE TABLE IF NOT EXISTS `tbl` (`tenantid` VARCHAR(1048576) COMMENT '', `create_day` DATE NOT NULL COMMENT '', `shopsite` VARCHAR(65533) NOT NULL COMMENT 'shopsite', `id` VARCHAR(65533) NOT NULL COMMENT 'shopsite id', `price` DECIMAL(38, 10) COMMENT 'price', `seq` INT COMMENT 'order', `use_status` SMALLINT COMMENT '0,1', `created_user` BIGINT COMMENT 'create user', `created_time` TIMESTAMP COMMENT 'create time', PRIMARY KEY (`tenantid`, `shopsite`, `id`)) COMMENT 'OLAP' PARTITIONED BY (`tenantid`) CLUSTERED BY (`tenantid`, `shopsite`, `id`) SORTED BY (`tenantid`, `shopsite`, `id`) INTO 10 BUCKETS PROPERTIES ('replication_num'='1', 'in_memory'='false', 'enable_persistent_index'='false', 'replicated_storage'='false', 'storage_medium'='HDD', 'compression'='LZ4')",
            read={
                "starrocks": """CREATE TABLE IF NOT EXISTS `tbl` (
    `tenantid` varchar(1048576) NULL COMMENT "",
    `create_day` date NOT NULL COMMENT "",
    `shopsite` varchar(65533) NOT NULL COMMENT "shopsite",
    `id` varchar(65533) NOT NULL COMMENT "shopsite id",
    `price` decimal128(38, 10) NULL COMMENT "price",
    `seq` int(11) NULL COMMENT "order",
    `use_status` smallint(6) NULL COMMENT "0,1",
    `created_user` bigint(20) NULL COMMENT "create user",
    `created_time` datetime NULL COMMENT "create time",
) ENGINE=OLAP
DUPLICATE KEY(tenantid)
PRIMARY KEY(`tenantid`, `shopsite`, `id`)
COMMENT "OLAP"
PARTITION BY (`tenantid`)
DISTRIBUTED BY HASH(`tenantid`, `shopsite`, `id`) BUCKETS 10
ORDER BY (`tenantid`, `shopsite`, `id`)
PROPERTIES (
    "replication_num" = "1",
    "in_memory" = "false",
    "enable_persistent_index" = "false",
    "replicated_storage" = "false",
    "storage_medium" = "HDD",
    "compression" = "LZ4"
)"""
            },
        )

    def test_dml(self):
        self.validate_all(
            "INSERT INTO a.b.c (`x`, `y`, `z`) VALUES (1, 'hello', CAST('2024-07-23 15:17:12' AS TIMESTAMP))",
            read={
                "presto": 'insert into a.b.c ("x", "y", "z") values (1, \'hello\', timestamp \'2024-07-23 15:17:12\')'
            },
        )

    def test_functions(self):
        self.validate_all(
            "SELECT APPROX_PERCENTILE(a, 0.9)",
            read={
                "presto": "select approx_percentile(a, 0.9)",
            },
            write={
                "clickzetta": "SELECT APPROX_PERCENTILE(a, 0.9)",
            },
        )
        self.validate_all(
            "SELECT CAST(`current_timestamp` / 1000 AS TIMESTAMP)",
            read={"clickhouse": "select toDateTime (current_timestamp / 1000)"},
        )
        self.validate_all(
            "SELECT CAST(`current_timestamp` / 1000 AS BIGINT) FROM tab",
            read={"clickhouse": "select CAST(current_timestamp / 1000, 'bigint') from tab"},
        )
        self.validate_all(
            "SELECT CAST(`current_timestamp` / 1000 AS DATE)",
            read={"clickhouse": "select toDate (current_timestamp / 1000)"},
        )
        self.validate_all(
            "SELECT TIMESTAMP_MILLIS(1415792726123)",
            read={"clickhouse": "SELECT fromUnixTimestamp64Milli(1415792726123)"},
        )
        # spark convert to_timestamp to cast syntax
        # https://github.com/tobymao/sqlglot/issues/4102
        to_start_of_func = ["Day", "Hour", "Minute", "Month", "Quarter", "Week", "Year", "Second"]
        for func in to_start_of_func:
            with self.subTest(f"Testing convert clickhouse toStartOfFunc: toStartOf{func}"):
                self.validate_all(
                    f"SELECT DATE_TRUNC('{func.upper()}', CAST('2023-04-21 10:20:30' AS TIMESTAMP))",
                    read={
                        "clickhouse": f"SELECT toStartOf{func}(toDateTime('2023-04-21 10:20:30'))"
                    },
                )
        self.validate_all(
            "SELECT REPLACE('data-science', '-', '_')",
            read={"clickhouse": "SELECT replaceAll('data-science', '-', '_')"},
        )

        clickhouse_to_clickzetta_json_func = [
            ("visitParamExtractRaw", "GET_JSON_OBJECT"),
            ("JSONExtractRaw", "GET_JSON_OBJECT"),
        ]
        json = """'{"a.c": {"b": 1}}'"""
        for name in clickhouse_to_clickzetta_json_func:
            with self.subTest(f"Testing convert clickhouse function: {name}"):
                self.validate_all(
                    rf"""SELECT {name[1]}({json}, '$[\'a.c\']')""",
                    read={"clickhouse": f"""SELECT {name[0]}({json}, 'a.c')"""},
                )

        clickhouse_to_clickzetta_json_func = [
            ("JSONExtractString", "JSON_EXTRACT_STRING"),
            ("visitParamExtractString", "JSON_EXTRACT_STRING"),
            ("visitParamExtractBool", "JSON_EXTRACT_BOOLEAN"),
            ("visitParamExtractInt", "JSON_EXTRACT_BIGINT"),
            ("visitParamExtractFloat", "JSON_EXTRACT_DOUBLE"),
            ("JSONExtractInt", "JSON_EXTRACT_BIGINT"),
            ("JSONExtractBool", "JSON_EXTRACT_BOOLEAN"),
            ("JSONExtractFloat", "JSON_EXTRACT_DOUBLE"),
        ]
        for name in clickhouse_to_clickzetta_json_func:
            with self.subTest(f"Testing convert clickhouse function: {name}"):
                self.validate_all(
                    rf"""SELECT {name[1]}(JSON {json}, '$[\'a.c\']')""",
                    read={"clickhouse": f"""SELECT {name[0]}({json}, 'a.c')"""},
                )

        self.validate_all(
            """SELECT JSON_EXTRACT(JSON '{"a": "hello", "b": [-100, 200.0, "hello"]}', '$.b')::ARRAY<JSON>""",
            read={
                "clickhouse": """SELECT JSONExtractArrayRaw('{"a": "hello", "b": [-100, 200.0, "hello"]}', 'b')"""
            },
        )
        self.validate_all(
            """COUNT_IF((retCode <> '1100'))""", read={"clickhouse": "countIf((retCode != '1100'))"}
        )
        self.validate_all(
            "SELECT left, right, MULTIIF(left < right, 'left is smaller', left > right, 'left is greater', left = right, 'Both equal', 'Null value') AS result FROM LEFT_RIGHT",
            read={
                "clickhouse": "SELECT left, right, multiIf(left < right, 'left is smaller', left > right, 'left is greater', left = right, 'Both equal', 'Null value') AS result FROM LEFT_RIGHT"
            },
        )
        self.validate_all("ISNOTNULL(x)", read={"clickhouse": "isNotNull(x)"})
        self.validate_all(
            "SELECT WM_CONCAT(',', x)",
            read={"postgres": "SELECT STRING_AGG(x, ',')"},
            write={
                "clickzetta": "SELECT WM_CONCAT(',', x)",
            },
        )
        self.validate_all(
            """SELECT DATE_FORMAT_PG(CURRENT_TIMESTAMP(), 'yyyy-"Q"Q')""",
            read={"postgres": """select to_char(current_timestamp, 'yyyy-"Q"Q')"""},
            write={
                "clickzetta": """SELECT DATE_FORMAT_PG(CURRENT_TIMESTAMP(), 'yyyy-"Q"Q')""",
            },
        )
        self.validate_all(
            "SELECT DATE_FORMAT_PG(CONVERT_TIMEZONE('America/Toronto', CAST(FROM_UNIXTIME(1692759280) AS TIMESTAMP)), 'yyyy-MM-dd HH24:MI:ss')",
            read={
                "postgres": "select to_char(to_timestamp(1692759280) at time zone 'America/Toronto', 'yyyy-MM-dd HH24:MI:ss');"
            },
            write={
                "clickzetta": "SELECT DATE_FORMAT_PG(CONVERT_TIMEZONE('America/Toronto', CAST(FROM_UNIXTIME(1692759280) AS TIMESTAMP)), 'yyyy-MM-dd HH24:MI:ss')",
            },
        )
        self.validate_all(
            "SELECT CAST(FROM_UNIXTIME(1415792726123 / 1000) AS TIMESTAMP)",
            read={"postgres": "select TO_TIMESTAMP(1415792726123/1000)"},
            write={
                "clickzetta": "SELECT CAST(FROM_UNIXTIME(1415792726123 / 1000) AS TIMESTAMP)",
            },
        )
        self.validate_all(
            r"SELECT DATE_FORMAT(CURRENT_TIMESTAMP(), 'yyyy-MM-dd\'T\'hh:mm:ss.SSSxxx')",
            read={"presto": "select to_iso8601(current_timestamp)"},
            write={
                "clickzetta": r"SELECT DATE_FORMAT(CAST(CURRENT_TIMESTAMP() AS TIMESTAMP), 'yyyy-MM-dd\'T\'hh:mm:ss.SSSxxx')",
            },
        )
        self.validate_all(
            "SELECT IF('a' = 0, NULL, 'a')",
            read={
                "presto": "select nullif('a',0)",
            },
            write={
                "clickzetta": "SELECT IF('a' = 0, NULL, 'a')",
            },
        )
        self.validate_all(
            "SELECT 1 / 0, TRY_CAST(a AS BIGINT)",
            read={
                "presto": "select try(1/0), try_cast(a as bigint)",
            },
            write={
                "clickzetta": "SELECT 1 / 0, TRY_CAST(a AS BIGINT)",
            },
        )
        self.validate_all(
            "SELECT IF(TRUE, 'a', NULL)",
            read={
                "presto": "select if(true, 'a')",
            },
            write={
                "clickzetta": "SELECT IF(TRUE, 'a', NULL)",
            },
        )
        self.validate_all(
            "SELECT POW(10, 2)",
            read={
                "presto": "select power(10, 2)",
            },
            write={
                "clickzetta": "SELECT POW(10, 2)",
            },
        )
        self.validate_all(
            "SELECT LAST_DAY(a)",
            read={
                "presto": "select last_day_of_month(a)",
            },
            write={
                "clickzetta": "SELECT LAST_DAY(a)",
            },
        )
        self.validate_all(
            'SELECT TO_JSON(JSON \'{"a":1,"b":2}\')',
            read={
                "presto": 'select json_format(json \'{"a":1,"b":2}\')',
            },
            write={
                "clickzetta": 'SELECT TO_JSON(JSON \'{"a":1,"b":2}\')',
            },
        )
        self.validate_all(
            """with a as (
  with a as (
    select 1 as i
  )
  select i as j from a
)
select j from a""",
            write={
                "clickzetta": "WITH a AS (WITH a AS (SELECT 1 AS i) SELECT i AS j FROM a) SELECT j FROM a",
            },
        )
        self.validate_all(
            "SELECT MAP_FROM_ENTRIES(COLLECT_LIST(STRUCT('a', DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))))",
            read={
                "presto": "select map_agg('a', date_trunc('day',NOW()))",
            },
            write={
                "clickzetta": "SELECT MAP_FROM_ENTRIES(COLLECT_LIST(STRUCT('a', DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))))",
            },
        )
        self.validate_all(
            "SELECT SEQUENCE(min_date, max_date, INTERVAL '1' DAY)",
            read={"presto": "select sequence(min_date,max_date,interval '1' day)"},
        )
        self.validate_all(
            "SELECT IF(TYPEOF(j) == 'json', (j::JSON)[2], PARSE_JSON(j::STRING)[2])",
            read={"presto": "select json_array_get(j,2)"},
        )
        self.validate_all(
            "SELECT IF(TYPEOF(IF(TYPEOF(j) == 'json', (j::JSON)[1], PARSE_JSON(j::STRING)[1])) == 'json',"
            " (IF(TYPEOF(j) == 'json', (j::JSON)[1], PARSE_JSON(j::STRING)[1])::JSON)[2],"
            " PARSE_JSON(IF(TYPEOF(j) == 'json', (j::JSON)[1], PARSE_JSON(j::STRING)[1])::STRING)[2])",
            read={"presto": "select json_array_get(json_array_get(j,1),2)"},
        )
        self.validate_identity(
            """SELECT CAST(JSON_EXTRACT(PARSE_JSON('{"a": 1}'), '$.a') AS STRING)""",
            """SELECT CAST(JSON_EXTRACT(JSON '{"a": 1}', '$.a') AS STRING)""",
        )
        # Starrocks Arrow function
        self.validate_all(
            """SELECT CAST(JSON_EXTRACT(fieldvalue, '$.00000000-0000-0000-0000-00000000') AS STRING) AS `code` FROM (SELECT JSON '{"00000000-0000-0000-0000-00000000":"code01"}' AS fieldvalue) AS t""",
            read={
                "starrocks": """SELECT CAST(fieldvalue -> '00000000-0000-0000-0000-00000000' AS VARCHAR) AS `code` FROM (SELECT PARSE_JSON('{"00000000-0000-0000-0000-00000000":"code01"}') as fieldvalue) as t"""
            },
        )
        self.validate_all(
            """SELECT CAST(JSON_EXTRACT(JSON '{"a": 1}', '$.a') AS STRING)""",
            read={"starrocks": """select cast(parse_json('{"a": 1}') -> 'a' as varchar)"""},
        )
        self.validate_all(
            "SELECT CEIL(5123.123, 1)", read={"starrocks": "SELECT ceiling(5123.123, 1)"}
        )
        self.validate_all(
            "SELECT CHAR(CAST('1' + 65 AS INT))", read={"starrocks": """select CHAR("1" + 65)"""}
        )
        self.validate_all(
            "SELECT COLLECT_LIST(pv) FROM VALUES (33), (334), (3), (6), (2) AS t(pv)",
            read={"starrocks": "select array_agg(pv) from values(33),(334),(3),(6),(2) as t(pv)"},
        )
        self.validate_all(
            "SELECT TO_TIMESTAMP(a, 'yyyy-MM-dd\\'T\\'HH:mm:ss\\'Z\\'')",
            read={"presto": "select parse_datetime(a, 'yyyy-MM-dd''T''HH:mm:ss''Z''')"},
        )
        # maxCompute DATETIME function
        self.validate_all("SELECT TO_TIMESTAMP(a)", read={"": "select DATETIME(a)"})
        # maxCompute GETDATE function
        self.validate_all("SELECT CURRENT_TIMESTAMP()", read={"": "select GETDATE()"})
        self.validate_all(
            "SELECT CAST('2020-01-01T00:00:00.000Z' AS TIMESTAMP)",
            read={"presto": "select from_iso8601_timestamp('2020-01-01T00:00:00.000Z')"},
        )
        self.validate_all(
            "SELECT * FROM t GROUP BY GROUPING SETS ((a), (b, c))",
            read={"presto": "select * from t group by grouping sets ((a), (b,c))"},
        )
        self.validate_all(
            "SELECT REGEXP_EXTRACT('aaaa', 'a|b|c')",
            read={"spark": "select regexp_extract('aaaa', 'a|b|c')"},
        )
        self.validate_all("SELECT LOG10(10)", read={"presto": "select log10(10)"})
        self.validate_all(
            "SELECT CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())",
            read={"presto": "select now() at time zone 'UTC'"},
        )
        self.validate_all("SELECT DAYOFWEEK(TO_DATE(d))", read={"spark": "select dayofweek(d)"})
        self.validate_all(
            "SELECT GROUPING_ID(a, b), GROUPING_ID(a, c) FROM foo GROUP BY GROUPING SETS ((a, b), (a, c))",
            read={
                "presto": "select grouping(a,b), grouping(a,c) from foo group by grouping sets ((a,b),(a,c))"
            },
        )

    def test_read_dialect_related_function(self):
        # aes_decrypt
        self.validate_all(
            "SELECT AES_DECRYPT_MYSQL(encrypted_string, key_string)",
            read={"mysql": "select AES_DECRYPT(encrypted_string, key_string)"},
        )
        self.validate_all(
            "SELECT AES_DECRYPT(encrypted_string, key_string)",
            read={"spark": "select AES_DECRYPT(encrypted_string, key_string)"},
        )

        # date_format
        self.validate_all(
            r"SELECT DATE_FORMAT_MYSQL(CURRENT_DATE, '%x-%v %a %W')",
            read={
                "presto": r"select DATE_FORMAT(CURRENT_DATE, '%x-%v %a %W')",
                "clickhouse": r"SELECT formatDateTime(CURRENT_DATE(), '%x-%v %a %W')",
            },
        )
        self.validate_all(
            "SELECT CAST(DATE_FORMAT_MYSQL(CAST('2024-08-22 14:53:12' AS TIMESTAMP), '%Y-%m-%d') AS DATE)",
            read={
                "presto": r"""SELECT CAST(date_format(cast('2024-08-22 14:53:12' as TIMESTAMP), '%Y-%m-%d') AS DATE)"""
            },
        )
        self.validate_all(
            "SELECT TIMESTAMP('2024-08-22 14:53:12'), DATE_FORMAT_MYSQL(TIMESTAMP('2024-08-22 "
            "14:53:12'), '%Y %M') /* expected: 2024 August */, DATE_FORMAT_MYSQL(TIMESTAMP('2024-08"
            "-22 14:53:12'), '%e') /* expected: 22 */, DATE_FORMAT_MYSQL(TIMESTAMP('2024-08-22 14:5"
            "3:12'), '%H %i %s') /* expected: 14 53 12 */",
            read={
                "presto": r"""select timestamp('2024-08-22 14:53:12')
                    , date_format(timestamp('2024-08-22 14:53:12'), '%Y %M') -- expected: 2024 August
                    , date_format(timestamp('2024-08-22 14:53:12'), '%e') -- expected: 22
                    , date_format(timestamp('2024-08-22 14:53:12'), '%H %i %s') -- expected: 14 53 12"""
            },
        )
        self.validate_all(
            r"SELECT DATE_FORMAT_PG(CURRENT_TIMESTAMP(), 'Mon-dd-YYYY,HH24:mi:ss')",
            read={"postgres": r"select to_char(now(), 'Mon-dd-YYYY,HH24:mi:ss')"},
        )
        self.validate_all(
            r"SELECT DATE_FORMAT_PG(CURRENT_TIMESTAMP(), 'YYYY-MM-DD')",
            read={"postgres": r"SELECT to_char(now(), 'YYYY-MM-DD');"},
        )
        self.validate_all(
            r"""SELECT DATE_FORMAT_PG(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI:SS')""",
            read={"postgres": r"""SELECT to_char(now(), 'YYYY-MM-DD HH24:MI:SS');"""},
        )
        self.validate_all(
            r"""SELECT DATE_FORMAT_PG(CURRENT_TIMESTAMP(), 'YYYY-MM-DD"T"HH24:MI:SS.MS')""",
            read={"postgres": r"""SELECT to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS.MS');"""},
        )

        # struct/tuple
        # https://prestodb.io/docs/current/functions/comparison.html#comparison-operators
        presto_binary_predicates = ["=", "!=", ">", ">=", "<", "<=", "<>"]
        spark_binary_predicates = ["=", "<>", ">", ">=", "<", "<=", "<>"]
        for i, predicate in enumerate(presto_binary_predicates):
            with self.subTest(f"Testing comparison operator: {predicate}"):
                spark_predicate = spark_binary_predicates[i]
                self.validate_all(
                    f"SELECT (1 AS col1, 'hello' AS col2) {spark_predicate} (2 AS col1, 'world' AS col2)",
                    read={"presto": f"select (1,'hello') {predicate} (2,'world')"},
                )
                self.validate_all(
                    f"SELECT (1, 'hello') {spark_predicate} (2, 'world') FROM (SELECT 1 AS a) AS t(a) GROUP BY GROUPING SETS ((a, a))",
                    read={
                        "spark": f"select (1,'hello') {spark_predicate} (2,'world') FROM (SELECT 1 AS a) AS t(a) GROUP BY GROUPING SETS ((a, a))"
                    },
                )
        # do not fill as __c? in values tuples
        self.validate_all(
            "SELECT * FROM VALUES (1, 'hello'), (2, 'world')",
            read={"presto": "select * from values (1,'hello'),(2,'world')"},
        )

        # date_add 3-arg
        self.validate_all(
            "SELECT TIMESTAMP_OR_DATE_ADD(LOWER('hour'), 1 + 2, CURRENT_TIMESTAMP())",
            read={"presto": "select date_add(lower('hour'), 1+2, now())"},
        )
        self.validate_all(
            "SELECT TIMESTAMP_OR_DATE_ADD('HOUR', 1 + 2, CURRENT_TIMESTAMP())",
            read={"presto": "select date_add('hour', 1+2, now())"},
        )
        self.validate_all(
            "SELECT TIMESTAMP_OR_DATE_ADD('HOUR', 1, CURRENT_TIMESTAMP())",
            read={
                "presto": "select DATE_ADD('hour', 1, now())",
                "starrocks": "select DATE_ADD(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)",
            },
        )
        self.validate_all(
            "SELECT TIMESTAMP_OR_DATE_ADD('DAY', 1, CAST('2001-08-22' AS DATE)), TIMESTAMP_OR_DATE_ADD('HOUR', 1, CURRENT_TIMESTAMP())",
            read={
                "presto": "select date_add('Day', 1, DATE '2001-08-22'), date_add('hour', 1, current_timestamp)"
            },
        )
        # dateadd 2-arg
        self.validate_all(
            "SELECT DATE_ADD(CURRENT_TIMESTAMP(), 1)",
            read={
                "spark": "SELECT DATE_ADD(CURRENT_TIMESTAMP(), 1)",
            },
        )

        # regexp_extract
        self.validate_all(
            "SELECT REGEXP_EXTRACT('aaaa', 'a|b|c', 0)",
            read={"presto": "select regexp_extract('aaaa', 'a|b|c')"},
            write={"clickzetta": "SELECT REGEXP_EXTRACT('aaaa', 'a|b|c', 0)"},
        )
        self.validate_all(
            "SELECT REGEXP_EXTRACT(`a`, 'a|b|c')",
            read={"presto": "SELECT REGEXP_EXTRACT(\"a\", 'a|b|c', 1)"},
            write={"clickzetta": "SELECT REGEXP_EXTRACT(`a`, 'a|b|c')"},
        )

        # rlike
        self.validate_all(
            r"SELECT RLIKE('1a 2b 14m', '\\d+b')",
            read={"presto": "SELECT regexp_like('1a 2b 14m', '\d+b')"},
        )
        self.validate_all(
            r"SELECT RLIKE('1a 2b 14m', '(\\d+)([ab]) ')",
            read={"presto": "SELECT regexp_like('1a 2b 14m', '(\d+)([ab]) ');"},
        )
        self.validate_all(
            r"SELECT RLIKE('new york', '(\\w)(\\w*)')",
            read={"presto": "SELECT regexp_like('new york', '(\w)(\w*)')"},
        )
        self.validate_all(
            r"SELECT RLIKE('1a 2b 14m', '\\s*[a-z]+\\s*')",
            read={"presto": "SELECT regexp_like('1a 2b 14m', '\s*[a-z]+\s*')"},
        )

        # day_of_week
        self.validate_all(
            "SELECT DAYOFWEEK_ISO(d), DAYOFWEEK_ISO(d), DAYOFYEAR(d), DAYOFYEAR(d), YEAROFWEEK(d), YEAROFWEEK(d)",
            read={
                "presto": "select dow(d), day_of_week(d), doy(d), day_of_year(d), yow(d), year_of_week(d)"
            },
        )

    def test_group_sql_expression(self):
        self.validate_identity(
            "SELECT a, AVG(b), AVG(c), COUNT(*) FROM VALUES ('A1', 2, 2) AS tab(a, b, c) GROUP BY a, b WITH ROLLUP",
            "SELECT a, AVG(b), AVG(c), COUNT(*) FROM VALUES ('A1', 2, 2) AS tab(a, b, c) GROUP BY ROLLUP (a, b)",
        )
        sql = (
            "SELECT a, AVG(b), AVG(c), COUNT(*) FROM VALUES ('A1', 2, 2), ('A1', 1, 1)"
            + " AS tab(a, b, c) GROUP BY CUBE (a, b)"
        )
        self.validate_all(
            sql,
            read={
                "hive": "SELECT a, AVG(b), AVG(c), COUNT(*) FROM VALUES ('A1', 2, 2), ('A1', 1, 1) "
                + "tab(a, b, c) GROUP BY a, b WITH CUBE",
                "clickzetta": sql,
            },
        )
        sql = (
            "SELECT a, b, AVG(c), COUNT(*) FROM VALUES ('A1', 2, 2), ('A1', 1, 1), ('A2', 3, 3)"
            + " AS tab(a, b, c) GROUP BY CUBE (a, b)"
        )
        self.validate_all(
            sql,
            read={
                "hive": """SELECT a, b, AVG(c), COUNT(*)
                        FROM VALUES ('A1', 2, 2), ('A1', 1, 1), ('A2', 3, 3) tab(a, b, c)
                    GROUP BY CUBE (a, b)""",
                "clickzetta": sql,
            },
        )

        sql = (
            "SELECT a, AVG(b), AVG(c), COUNT(*) FROM VALUES ('A1', 2, 2), ('A1', 1, 1), ('A2', 3, 3),"
            + " ('A1', 1, 1) AS tab(a, b, c) GROUP BY ROLLUP (a, b)"
        )
        self.validate_all(
            sql,
            read={
                "hive": "SELECT a, AVG(b), AVG(c), COUNT(*) FROM VALUES ('A1', 2, 2), ('A1', 1, 1), ('A2', 3, 3), ('A1', 1, 1)"
                + " AS tab(a, b, c) GROUP BY a, b WITH ROLLUP",
                "clickzetta": sql,
            },
        )

        sql = "SELECT a, SUM(c) FROM (SELECT 'A1' AS a, 1 AS b, 1 AS c UNION SELECT 'A2' AS a, 2 AS b, 2 AS c) AS tab GROUP BY GROUPING SETS ((), (a))"
        self.validate_all(
            sql,
            read={
                "hive": """SELECT a, sum(c) FROM (select 'A1' as a, 1 as b, 1 as c union select 'A2' as a, 2 as b, 2 as c) tab GROUP BY a GROUPING SETS ((), (a))""",
                "clickzetta": sql,
            },
        )
        sql = (
            "SELECT a, b, COUNT(*) FROM VALUES ('A1', 2, 2), ('A1', 1, 1), ('A2', 3, 3), ('A1', 1, 1)"
            + " AS tab(a, b, c) GROUP BY CUBE (c), ROLLUP (a, b) ORDER BY a, b LIMIT 10"
        )
        self.validate_all(
            sql,
            read={
                "hive": """SELECT a, b, count(*)
                    FROM VALUES ('A1', 2, 2), ('A1', 1, 1), ('A2', 3, 3), ('A1', 1, 1) tab(a, b, c)
                    group by rollup(a,b), cube(c) order by a, b LIMIT 10""",
                "clickzetta": sql,
            },
        )

    def test_unnest(self):
        # From unnest
        self.validate_all(
            "SELECT * FROM VALUES ('a', 1), ('b', 2), ('c', 3) AS t(s, i)",
            read={"presto": "select * from unnest(array[('a',1),('b',2),('c',3)]) as t(s,i)"},
        )
        self.validate_all(
            "SELECT i FROM EXPLODE(SEQUENCE(-3, 0)) AS t(i)",
            read={"presto": "select i from unnest(sequence(-3,0)) as t(i)"},
        )
        self.validate_all(
            "SELECT * FROM EXPLODE(SEQUENCE(-3, 0))",
            read={"presto": "select * from unnest(sequence(-3,0))"},
        )
        self.validate_all(
            r"""SELECT * FROM UNNEST(ARRAY('John', 'Jane', 'Jim', 'Jamie'), ARRAY(24, 25, 26, 27)) AS t(name, age)""",
            read={
                "presto": r"""SELECT * FROM UNNEST(array('John','Jane','Jim','Jamie'), array(24,25,26,27)) AS t(name, age)""",
            },
            write={
                "clickzetta": "SELECT * FROM UNNEST(ARRAY('John', 'Jane', 'Jim', 'Jamie'), ARRAY(24, 25, 26, 27)) AS t(name, age)",
            },
        )
        # Join with unnest
        self.validate_all(
            "SELECT s.n FROM tmp LATERAL VIEW EXPLODE(SEQUENCE(min_date, max_date, INTERVAL '1' DAY)) s AS n",
            read={
                "presto": "select s.n from tmp cross join unnest(sequence(min_date,max_date, INTERVAL '1' DAY)) s (n)"
            },
        )
        self.validate_all(
            "SELECT student, score FROM tests LATERAL VIEW EXPLODE(scores) t AS score",
            read={
                "presto": "SELECT student, score FROM tests CROSS JOIN UNNEST(scores) AS t (score)"
            },
        )
        # Use UNNEST to convert into multiple columns
        # see: https://docs.starrocks.io/docs/sql-reference/sql-functions/array-functions/unnest/
        self.validate_all(
            r"""SELECT id, t.type, t.scores FROM example_table LATERAL VIEW INLINE(ARRAYS_ZIP(SPLIT(type, CONCAT('\\Q', ';')), scores)) t AS type, scores""",
            read={
                "starrocks": r"""SELECT id, t.type, t.scores FROM example_table, unnest(split(type, ";"), scores) AS t(type,scores)""",
            },
            write={
                "clickzetta": r"""SELECT id, t.type, t.scores FROM example_table LATERAL VIEW INLINE(ARRAYS_ZIP(SPLIT(type, CONCAT('\\Q', ';')), scores)) t AS type, scores""",
            },
        )
        self.validate_all(
            r"""SELECT id, t.type, t.scores FROM example_table LATERAL VIEW INLINE(ARRAYS_ZIP(SPLIT(type, CONCAT('\\Q', ';')), scores)) t AS type, scores""",
            read={
                "starrocks": r"""SELECT id, t.type, t.scores FROM example_table CROSS JOIN LATERAL unnest(split(type, ";"), scores) AS t(type,scores)""",
            },
            write={
                "clickzetta": r"""SELECT id, t.type, t.scores FROM example_table LATERAL VIEW INLINE(ARRAYS_ZIP(SPLIT(type, CONCAT('\\Q', ';')), scores)) t AS type, scores""",
            },
        )
        self.validate_all(
            "SELECT a, b, c, a1, a2 FROM example_table LATERAL VIEW INLINE(ARRAYS_ZIP(a, b, c)) t AS a, b, c",
            read={
                "presto": "SELECT a,b,c,a1,a2 FROM example_table cross join unnest(a,b,c) as t(a,b,c)"
            },
        )

        lateral_explode_sqls = [
            "SELECT id, t.col FROM tbl, UNNEST(scores) AS t(col)",
            "SELECT id, t.col FROM tbl CROSS JOIN LATERAL UNNEST(scores) AS t(col)",
        ]
        clickzetta_lateral_explode_sqls = (
            "SELECT id, t.col FROM tbl LATERAL VIEW EXPLODE(scores) t AS col"
        )

        for sql in lateral_explode_sqls:
            with self.subTest(f"Testing Starrocks roundtrip & transpilation of: {sql}"):
                self.validate_all(
                    clickzetta_lateral_explode_sqls,
                    read={
                        "starrocks": sql,
                    },
                    write={
                        "clickzetta": clickzetta_lateral_explode_sqls,
                    },
                )

        self.validate_all(
            "SELECT EXPLODE(ARRAY(1, 2, 3))",
            read={
                "clickhouse": "SELECT arrayJoin([1, 2, 3])",
                "postgres": "SELECT UNNEST(ARRAY[1, 2, 3])",
            },
            write={
                "clickzetta": "SELECT EXPLODE(ARRAY(1, 2, 3))",
            },
        )
        self.validate_all(
            "SELECT COUNT(DISTINCT col1) FROM tbl",
            read={
                "clickhouse": "SELECT uniqExact(col1) FROM tbl",
            },
        )

    def test_hash_func(self):
        self.validate_all(
            "SELECT SUM(MURMURHASH3_32('test'))",
            read={"starrocks": "select sum(murmur_hash3_32('test'))"},
            write={"clickzetta": "SELECT SUM(MURMURHASH3_32('test'))"},
        )
