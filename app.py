import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="SIGA — TecnoHogar S.A.S.",
    layout="wide",
)

DB_PATH = "tecnohogar_siga.db"


@st.cache_resource
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            categoria TEXT NOT NULL,
            stock_actual INTEGER NOT NULL DEFAULT 0,
            stock_minimo INTEGER NOT NULL DEFAULT 5,
            precio_unitario REAL NOT NULL DEFAULT 0.0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('ENTRADA', 'SALIDA')),
            cantidad INTEGER NOT NULL CHECK(cantidad > 0),
            observacion TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (producto_id) REFERENCES productos(id)
        )
        """
    )
    cur.execute("SELECT COUNT(*) AS total FROM productos")
    total = cur.fetchone()["total"]
    if total == 0:
        productos_iniciales = [
            ("Nevera No Frost 300L", "Electrodomésticos", 12, 5, 1650000.0),
            ("Lavadora Carga Superior 18kg", "Electrodomésticos", 4, 5, 1420000.0),
            ("Televisor Smart TV 55'' 4K", "Tecnología", 9, 4, 1890000.0),
            ("Microondas Digital 25L", "Electrodomésticos", 3, 4, 380000.0),
            ("Portátil 15.6'' Core i5", "Tecnología", 6, 3, 2350000.0),
            ("Barra de Sonido Bluetooth", "Tecnología", 2, 4, 520000.0),
        ]
        cur.executemany(
            """
            INSERT INTO productos (nombre, categoria, stock_actual, stock_minimo, precio_unitario)
            VALUES (?, ?, ?, ?, ?)
            """,
            productos_iniciales,
        )
    cur.execute("DROP VIEW IF EXISTS vista_alertas_stock")
    cur.execute(
        """
        CREATE VIEW vista_alertas_stock AS
        SELECT
            id,
            nombre,
            categoria,
            stock_actual,
            stock_minimo,
            (stock_minimo - stock_actual) AS faltante,
            precio_unitario
        FROM productos
        WHERE stock_actual <= stock_minimo
        """
    )
    conn.commit()


def cargar_productos(conn, categoria="Todas"):
    if categoria and categoria != "Todas":
        query = """
            SELECT id, nombre, categoria, stock_actual, stock_minimo, precio_unitario
            FROM productos
            WHERE categoria = ?
            ORDER BY nombre
        """
        return pd.read_sql_query(query, conn, params=(categoria,))
    query = """
        SELECT id, nombre, categoria, stock_actual, stock_minimo, precio_unitario
        FROM productos
        ORDER BY nombre
    """
    return pd.read_sql_query(query, conn)


def cargar_movimientos(conn, limite=30):
    query = """
        SELECT
            m.id,
            p.nombre AS producto,
            p.categoria,
            m.tipo,
            m.cantidad,
            m.observacion,
            m.fecha
        FROM movimientos m
        JOIN productos p ON p.id = m.producto_id
        ORDER BY m.id DESC
        LIMIT ?
    """
    return pd.read_sql_query(query, conn, params=(limite,))


def registrar_movimiento(conn, producto_id, tipo, cantidad, observacion=""):
    if cantidad <= 0:
        return False, "La cantidad debe ser mayor que cero."

    cur = conn.cursor()
    cur.execute(
        "SELECT nombre, stock_actual FROM productos WHERE id = ?",
        (producto_id,),
    )
    prod = cur.fetchone()
    if prod is None:
        return False, "Producto no encontrado."

    stock_actual = prod["stock_actual"]
    nombre_prod = prod["nombre"]

    if tipo == "SALIDA" and cantidad > stock_actual:
        return (
            False,
            f"Stock insuficiente para '{nombre_prod}'. Disponible: {stock_actual} unidades.",
        )

    nuevo_stock = stock_actual + cantidad if tipo == "ENTRADA" else stock_actual - cantidad

    cur.execute(
        "UPDATE productos SET stock_actual = ? WHERE id = ?",
        (nuevo_stock, producto_id),
    )
    cur.execute(
        """
        INSERT INTO movimientos (producto_id, tipo, cantidad, observacion)
        VALUES (?, ?, ?, ?)
        """,
        (producto_id, tipo, cantidad, observacion.strip()),
    )
    conn.commit()
    return True, f"Movimiento registrado. Nuevo stock de '{nombre_prod}': {nuevo_stock} unidades."


conn = get_connection()
init_db(conn)

st.title("SIGA — TecnoHogar S.A.S.")
st.caption("Sistema de Gestión de Inventario · Electrodomésticos y Tecnología")

tab_inicio, tab_mov, tab_inv, tab_alertas = st.tabs(
    ["Inicio", "Registrar movimiento", "Inventario", "Alertas"]
)

with tab_inicio:
    df_all = cargar_productos(conn, "Todas")
    df_alertas_base = pd.read_sql_query("SELECT * FROM vista_alertas_stock", conn)
    valor_total = (df_all["stock_actual"] * df_all["precio_unitario"]).sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Referencias activas", len(df_all))
    c2.metric("Productos en alerta", len(df_alertas_base))
    c3.metric("Valor del inventario (COP)", f"${valor_total:,.0f}")

    st.subheader("Últimos movimientos")
    df_mov = cargar_movimientos(conn, limite=10)
    if df_mov.empty:
        st.info("Aún no hay movimientos registrados.")
    else:
        st.dataframe(df_mov, use_container_width=True, hide_index=True)

with tab_mov:
    st.subheader("Registrar entrada o salida de inventario")
    df_prod = cargar_productos(conn, "Todas")
    nombres_productos = df_prod["nombre"].tolist()
    mapa_id = dict(zip(df_prod["nombre"], df_prod["id"]))

    with st.form("form_movimiento"):
        producto_sel = st.selectbox("Producto", options=nombres_productos)
        tipo_sel = st.selectbox("Tipo de movimiento", options=["ENTRADA", "SALIDA"])
        cantidad_sel = st.number_input("Cantidad", min_value=1, step=1, value=1)
        obs_sel = st.text_input("Observación (opcional)")
        enviado = st.form_submit_button("Guardar movimiento")

    if enviado:
        ok, mensaje = registrar_movimiento(
            conn,
            producto_id=mapa_id[producto_sel],
            tipo=tipo_sel,
            cantidad=int(cantidad_sel),
            observacion=obs_sel,
        )
        if ok:
            st.success(mensaje)
            st.rerun()
        else:
            st.error(mensaje)

with tab_inv:
    st.subheader("Catálogo e inventario actual")
    categorias = ["Todas"] + sorted(
        cargar_productos(conn, "Todas")["categoria"].unique().tolist()
    )
    cat_sel = st.selectbox("Filtrar por categoría", options=categorias)
    df_filtrado = cargar_productos(conn, cat_sel)
    st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

with tab_alertas:
    st.subheader("Alertas de stock mínimo")
    umbral_extra = st.slider(
        "Margen adicional sobre stock mínimo",
        min_value=0,
        max_value=10,
        value=0,
        step=1,
    )
    query_alerta = """
        SELECT
            nombre AS producto,
            categoria,
            stock_actual,
            stock_minimo,
            (stock_minimo + ?) AS umbral_evaluado,
            ((stock_minimo + ?) - stock_actual) AS unidades_por_pedir
        FROM productos
        WHERE stock_actual <= (stock_minimo + ?)
        ORDER BY stock_actual ASC
    """
    df_alerta = pd.read_sql_query(
        query_alerta, conn, params=(umbral_extra, umbral_extra, umbral_extra)
    )
    if df_alerta.empty:
        st.success("No hay productos por debajo del umbral seleccionado.")
    else:
        st.dataframe(df_alerta, use_container_width=True, hide_index=True)
        st.bar_chart(df_alerta.set_index("producto")[["stock_actual", "umbral_evaluado"]])
