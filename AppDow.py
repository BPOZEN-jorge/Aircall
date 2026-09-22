import io
import os
import re
import time
import zipfile
from datetime import datetime

import requests
import streamlit as st
from requests.auth import HTTPBasicAuth

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Monitor y Descargador Aircall", layout="wide")


# --- MÓDULO DE AUTENTICACIÓN (LOGIN SOLO CONTRASEÑA) ---
def verificar_password():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        st.title("🔒 Acceso Restringido")
        st.subheader("Por favor, ingresa la contraseña para continuar")

        with st.form("form_login"):
            password_input = st.text_input("Contraseña:", type="password")
            submit_button = st.form_submit_button("Ingresar")

            if submit_button:
                if password_input == st.secrets["auth"]["password"]:
                    st.session_state.autenticado = True
                    st.success("Acceso concedido")
                    st.rerun()
                else:
                    st.error("❌ Contraseña incorrecta")
        return False
    return True


# Si no está autenticado, detiene la ejecución del resto del script
if not verificar_password():
    st.stop()

# Botón para cerrar sesión en la barra lateral
if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.autenticado = False
    st.rerun()

# --- Configuración de la API de Aircall ---
API_ID = st.secrets["aircall"]["api_id"]
API_TOKEN = st.secrets["aircall"]["api_token"]
BASE_URL = "https://api.aircall.io/v1/calls"

st.title("📊 Consulta, Visor y Descarga de Llamadas - Aircall")

# --- Inicializar el Estado de la Sesión (Session State) ---
if "datos_tabla" not in st.session_state:
    st.session_state.datos_tabla = None
if "fecha_buscada" not in st.session_state:
    st.session_state.fecha_buscada = None


# --- Función para limpiar texto genérico (Nombre de asesor) ---
def limpiar_nombre_asesor(texto):
    if not texto:
        return "SinAgente"
    # Reemplaza caracteres no permitidos en archivos por guion bajo
    return re.sub(r'[\\/*?:"<>| ]', "_", str(texto))


# --- Función para limpiar el número de teléfono (SOLO DÍGITOS) ---
def limpiar_telefono_solo_digitos(texto):
    if not texto:
        return "SinNumero"
    # Deja únicamente dígitos del 0 al 9 (elimina +, -, espacios, guiones, etc.)
    digitos = re.sub(r"\D", "", str(texto))
    return digitos if digitos else "SinNumero"


# --- Función para procesar y estructurar los datos filtrados ---
def procesar_llamadas_para_tabla(lista_llamadas):
    tags_permitidos = {
        "Ventas - Acepta oferta",
        "Ventas - Acepta Oferta - Whatsapp",
        "Ventas - Acepta Oferta - Digital",
        "Ventas - Acepta Digital Ventas Orgánico",
    }

    llamadas_procesadas = []

    for llamada in lista_llamadas:
        tags_llamada = [
            t.get("name") for t in llamada.get("tags", []) if isinstance(t, dict)
        ]
        if not any(tag in tags_permitidos for tag in tags_llamada):
            continue

        url_audio = llamada.get("recording") or llamada.get("voicemail")
        if not url_audio:
            continue

        timestamp = llamada.get("started_at")
        fecha_llamada = (
            datetime.fromtimestamp(timestamp)
            if timestamp
            else datetime.today()
        )
        fecha_formateada = fecha_llamada.strftime("%Y-%m-%d %H:%M:%S")

        # 1. ID de la llamada
        id_llamada = llamada.get("id", "SinID")

        # 2. Nombre del Asesor/Agente
        usuario_obj = llamada.get("user")
        nombre_usuario = (
            usuario_obj.get("name", "SinAgente")
            if usuario_obj and isinstance(usuario_obj, dict)
            else "SinAgente"
        )
        asesor_limpio = limpiar_nombre_asesor(nombre_usuario)

        # 3. Número de teléfono de la contraparte (Cliente) - SOLO DÍGITOS
        numero_cliente = llamada.get("raw_digits")
        if not numero_cliente:
            direccion = llamada.get("direction")
            if direccion == "inbound":
                numero_cliente = llamada.get("from", "SinNumero")
            else:
                numero_cliente = llamada.get("to", "SinNumero")

        telefono_solo_digitos = limpiar_telefono_solo_digitos(numero_cliente)

        # 4. Nombre final del archivo: ID - ASESOR - NUMERO.mp3
        nombre_archivo = (
            f"{id_llamada}-{asesor_limpio}-{telefono_solo_digitos}.mp3"
        )

        linea_obj = llamada.get("number", {})
        linea_destino = (
            linea_obj.get("name", "Sin Línea")
            if isinstance(linea_obj, dict)
            else "Sin Línea"
        )

        registro = {
            "ID Call": id_llamada,
            "Dirección": llamada.get("direction"),
            "Estado": llamada.get("status"),
            "Motivo Pérdida": llamada.get("missed_call_reason") or "N/A",
            "Fecha / Hora Inicio": fecha_formateada,
            "fecha_dt": fecha_llamada,
            "Duración (Seg)": llamada.get("duration", 0),
            "Teléfono Cliente": numero_cliente or "SinNumero",
            "Línea Destino": linea_destino,
            "Agente Asignado": nombre_usuario,
            "Tags (Etiquetas)": (
                ", ".join(tags_llamada) if tags_llamada else "Sin Tags"
            ),
            "País": llamada.get("country_code_a2", "N/A"),
            "url_audio": url_audio,
            "nombre_archivo_descarga": nombre_archivo,
        }
        llamadas_procesadas.append(registro)

    return llamadas_procesadas


# --- Función para empaquetar archivos en un archivo ZIP directamente en memoria ---
def generar_zip_en_memoria(lista_procesada):
    zip_buffer = io.BytesIO()
    total_items = len(lista_procesada)
    bar_progreso = st.progress(0)

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for idx, item in enumerate(lista_procesada):
            fecha_dt = item["fecha_dt"]
            ano = fecha_dt.strftime("%Y")
            mes = fecha_dt.strftime("%m-%B")
            dia = fecha_dt.strftime("%d")

            ruta_dentro_del_zip = os.path.join(
                "Llamadas_Aircall",
                ano,
                mes,
                dia,
                item["nombre_archivo_descarga"],
            )

            try:
                res = requests.get(item["url_audio"])
                if res.status_code == 200:
                    zip_file.writestr(ruta_dentro_del_zip, res.content)
                time.sleep(0.1)
            except Exception as e:
                st.error(
                    f"Error procesando {item['nombre_archivo_descarga']}: {e}"
                )

            bar_progreso.progress((idx + 1) / total_items)

    zip_buffer.seek(0)
    return zip_buffer


# --- Petición a la API de Aircall con manejo anti-error 429 ---
def obtener_llamadas(desde, hasta):
    todas_las_llamadas = []
    url_actual = BASE_URL
    params = {"from": desde, "to": hasta, "order": "desc", "per_page": 50}

    while url_actual:
        try:
            if url_actual == BASE_URL:
                response = requests.get(
                    url_actual,
                    auth=HTTPBasicAuth(API_ID, API_TOKEN),
                    params=params,
                )
            else:
                response = requests.get(
                    url_actual, auth=HTTPBasicAuth(API_ID, API_TOKEN)
                )

            if response.status_code == 200:
                data = response.json()
                todas_las_llamadas.extend(data.get("calls", []))
                url_actual = data.get("meta", {}).get("next_page_link")
                time.sleep(0.3)

            elif response.status_code == 429:
                st.warning(
                    "⚠️ Límite de peticiones alcanzado (Error 429). Esperando"
                    " 5 segundos para reintentar..."
                )
                time.sleep(5)
                continue
            else:
                st.error(
                    f"Error de API: {response.status_code} - {response.text}"
                )
                break
        except Exception as e:
            st.error(f"Error de conexión: {e}")
            break

    return todas_las_llamadas


# --- Interfaz en Barra Lateral ---
st.sidebar.header("Filtros de Búsqueda")
fecha_seleccionada = st.sidebar.date_input(
    "Selecciona una fecha", datetime.today()
)

inicio_dia = int(time.mktime(fecha_seleccionada.timetuple()))
fin_dia = inicio_dia + 86399

# --- Disparador del Botón de Búsqueda ---
if st.sidebar.button("🔍 Filtrar y Tabular Llamadas"):
    with st.spinner("Buscando y filtrando registros en Aircall..."):
        llamadas_raw = obtener_llamadas(inicio_dia, fin_dia)

    if llamadas_raw:
        st.session_state.datos_tabla = procesar_llamadas_para_tabla(
            llamadas_raw
        )
        st.session_state.fecha_buscada = fecha_seleccionada
    else:
        st.session_state.datos_tabla = []
        st.sidebar.warning(
            f"⚠️ No se encontraron llamadas en Aircall para el día"
            f" {fecha_seleccionada}."
        )

# --- RENDERIZADO DE RESULTADOS ---
if st.session_state.datos_tabla:
    cantidad_llamadas = len(st.session_state.datos_tabla)

    st.write(f"### 📅 Resultados para el día: {st.session_state.fecha_buscada}")
    st.metric(
        label="Cantidad de llamadas filtradas (Ventas)", value=cantidad_llamadas
    )

    st.markdown("---")

    col_descarga, col_vacia = st.columns([2, 3])
    with col_descarga:
        with st.spinner("Preparando archivo ZIP para descarga..."):
            zip_audio_data = generar_zip_en_memoria(
                st.session_state.datos_tabla
            )

            st.download_button(
                label="📦 Descargar TODAS las llamadas (.ZIP)",
                data=zip_audio_data,
                file_name=(
                    f"Llamadas_Aircall_{st.session_state.fecha_buscada}.zip"
                ),
                mime="application/zip",
                key="descarga_masiva_zip",
            )
            st.caption(
                "ℹ️ El ZIP conservará la estructura organizada de carpetas por"
                " Año/Mes/Día al descomprimirse en tu equipo."
            )

    st.markdown("---")

    cols_header = st.columns(
        [1.2, 0.9, 0.9, 1.2, 1.6, 0.8, 1.3, 1.5, 1.3, 1.6, 0.5, 2.5, 1.2]
    )
    titulos = [
        "ID Call",
        "Dirección",
        "Estado",
        "Motivo",
        "Fecha Inicio",
        "Duración",
        "Tel. Cliente",
        "Línea Destino",
        "Agente",
        "Tags",
        "País",
        "Reproductor",
        "Acción",
    ]

    for col, tit in zip(cols_header, titulos):
        col.markdown(f"**{tit}**")
    st.markdown("---")

    for item in st.session_state.datos_tabla:
        cols_fila = st.columns(
            [1.2, 0.9, 0.9, 1.2, 1.6, 0.8, 1.3, 1.5, 1.3, 1.6, 0.5, 2.5, 1.2]
        )

        cols_fila[0].write(str(item["ID Call"]))
        cols_fila[1].write(item["Dirección"])
        cols_fila[2].write(item["Estado"])
        cols_fila[3].write(item["Motivo Pérdida"])
        cols_fila[4].write(item["Fecha / Hora Inicio"])
        cols_fila[5].write(f"{item['Duración (Seg)']}s")
        cols_fila[6].write(item["Teléfono Cliente"])
        cols_fila[7].write(item["Línea Destino"])
        cols_fila[8].write(item["Agente Asignado"])
        cols_fila[9].write(item["Tags (Etiquetas)"])
        cols_fila[10].write(item["País"])

        with cols_fila[11]:
            st.audio(item["url_audio"], format="audio/mp3")

        with cols_fila[12]:
            try:

                @st.cache_data(show_spinner=False)
                def descargar_audio_bytes(url):
                    return requests.get(url).content

                audio_bytes = descargar_audio_bytes(item["url_audio"])

                st.download_button(
                    label="📥 Bajar",
                    data=audio_bytes,
                    file_name=item["nombre_archivo_descarga"],
                    mime="audio/mp3",
                    key=f"dl_{item['ID Call']}",
                )
            except Exception:
                st.error("Error")

elif st.session_state.datos_tabla == []:
    st.info(
        "ℹ️ No hay llamadas con los tags de Ventas específicos para la fecha"
        " seleccionada."
    )