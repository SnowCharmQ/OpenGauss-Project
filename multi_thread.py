import time
import psycopg2

import decorator2
from connection import OpenGaussConnection, SqliteConnection
from opengauss_thread import OpenGaussLogThread, OpenGaussThread


def multi_thread(opengauss_properties, sqlite_properties, error_log, info_log, sqls_log, is_record_sqls):
    opengauss = OpenGaussConnection(opengauss_properties, error_log, info_log)
    sqlite = SqliteConnection(sqlite_properties, error_log, info_log)

    conn_sqlite = sqlite.getconn()

    dbusername = opengauss_properties['database.user']
    dbschema = opengauss_properties['database.schema']
    conn_opengauss = opengauss.getconn()
    cursor_opengauss = conn_opengauss.cursor()
    try:
        cursor_opengauss.execute("create schema %s authorization %s;" % (dbschema, dbusername))
        cursor_opengauss.execute("grant usage on schema %s to %s;" % (dbschema, dbusername))
        conn_opengauss.commit()
        cursor_opengauss.close()
        opengauss.putconn(conn_opengauss)
    except psycopg2.errors.DuplicateSchema as e:
        info_log.info(e)
        cursor_opengauss.close()
        opengauss.putconn(conn_opengauss)

    print("The data migration operation is in progress...")
    time_start = time.time()

    cursor_sqlite = conn_sqlite.cursor()
    all_table = cursor_sqlite.execute("select * from sqlite_master where type = 'table';")
    create_sqls = []
    for row in all_table:
        s = row[4]
        s = s.replace('\n', '').replace('\r', '').replace('   ', ' ')
        create_sqls.append(s + ";")
    try:
        conn_opengauss = opengauss.getconn()
        cursor_opengauss = conn_opengauss.cursor()
        cursor_opengauss.execute("set search_path to %s;" % dbschema)
        auto_incre = {}
        for sql in create_sqls:
            if sql.upper().startswith("CREATE"):

                index = sql.find('(')
                table_name = sql[13:index]

                if sql.find("AUTOINCREMENT") != -1 or sql.find("autoincrement") != -1:
                    cursor_opengauss.execute(
                        "CREATE SEQUENCE sq_" + table_name + "  START 1 INCREMENT 1 CACHE 20;")  # 创建自增序列

                newsql = decorator2.createWithoutFK(sql)
                newsql = decorator2.autoIncrement(newsql)


                cursor_opengauss.execute(newsql)

            if is_record_sqls:
                sqls_log.info(sql)
        conn_opengauss.commit()
    except Exception as e:
        error_log.error(e)
    finally:
        if conn_opengauss is not None:
            opengauss.putconn(conn_opengauss)

    count = 0
    sqls = []
    thread_list = []
    for sql in conn_sqlite.iterdump():
        if sql.upper().startswith("CREATE"):
            continue
        sql = decorator2.Insert(sql)
        sqls.append(sql)
        count += 1
        if count == 100:
            if is_record_sqls:
                t = OpenGaussLogThread(opengauss, sqls, dbschema, error_log, sqls_log)
            else:
                t = OpenGaussThread(opengauss, sqls, dbschema, error_log)
            thread_list.append(t)
            t.start()
            sqls = []
            count = 0
    if is_record_sqls:
        t = OpenGaussLogThread(opengauss, sqls, dbschema, error_log, sqls_log)
    else:
        t = OpenGaussThread(opengauss, sqls, dbschema, error_log)
    thread_list.append(t)
    t.start()
    for t in thread_list:
        t.join()

    try:
        conn_opengauss = opengauss.getconn()
        cursor_opengauss = conn_opengauss.cursor()
        cursor_opengauss.execute("set search_path to %s;" % dbschema)
        for create_sql in create_sqls:
            sqls = decorator2.alterFK(create_sql)
            for alter_sql in sqls:
                cursor_opengauss.execute(alter_sql)
                if is_record_sqls:
                    sqls_log.info(alter_sql)
        conn_opengauss.commit()
    except Exception as e:
        error_log.error(e)
    finally:
        if conn_opengauss is not None:
            opengauss.putconn(conn_opengauss)

    time_end = time.time()

    time_c = time_end - time_start
    print('Time Cost = %.2f seconds' % time_c)
