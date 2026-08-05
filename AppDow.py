import streamlit as st
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
import time
import re

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Monitor de Llamadas Aircall", layout="wide")

# --- MÓDULO DE AUTENTICACIÓN (LOGIN) ---
def verificar_password():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        st.title("🔒 Acceso Restringido")
        st.subheader("Por favor, inicia sesión para acceder al monitor")
        
        with st.form("form_login"):
            password_input = st.text_input("Contraseña de acceso:", type="password")
            submit_button = st.form_submit_button("Ingresar")
            
            if submit_button:
                # Compara con la contraseña definida en st.secrets
                if password_input == st.secrets["auth"]["password"]:
                    st.session_state.autenticado = True
                    st.success("Acceso concedido")
                    st.rerun()
                else:
                    st.error("❌ Contraseña incorrecta")
        return False
    return True

# Si el usuario no ha ingresado la contraseña correcta, detiene la app aquí
if not verificar_password():
    st.stop()

# --- A PARTIR DE AQUÍ SE EJECUTA SI ESTÁ AUTENTICADO ---

# Botón para cerrar sesión en la barra lateral
if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.autenticado = False
    st.rerun()

# --- Configuración de la API de Aircall desde Secrets ---
API_ID = st.secrets["aircall"]["api_id"]
API_TOKEN = st.secrets["aircall"]["api_token"]
BASE_URL = "https://api.aircall.io/v1/calls"

st.title("📊 Consulta de Llamadas con Descarga Estructurada - Aircall")

# --- Inicializar el Estado de la Sesión (Session State) ---
if "datos_tabla" not in st.session_state:
    st.session_state.datos_tabla = None
if "fecha_buscada" not in st.session_state:
    st.session_state.fecha_buscada = None

# --- Función para limpiar caracteres no válidos en nombres de archivos ---
def limpiar_nombre_archivo(texto):
    if not texto:
        return "Desconocido"
    return re.sub(r'[\\/*?:"<>| ]', '_', str(texto))

# --- Función para procesar y estructurar los datos ---
def procesar_llamadas_para_tabla(lista_llamadas):
    tags_permitidos = {
        "Ventas - Acepta oferta",
        "Ventas - Acepta Oferta - Whatsapp",
        "Ventas - Acepta Oferta - Digital"
    }
    
    llamadas_procesadas = []
    
    for llamada in lista_llamadas:
        tags_llamada = [t.get("name") for t in llamada.get("tags", []) if isinstance(t, dict)]
        if not any(tag in tags_permitidos for tag in tags_llamada):
            continue
            
        url_audio = llamada.get("recording") or llamada.get("voicemail")
        if not url_audio:
            continue
            
        timestamp = llamada.get("started_at")
        fecha_llamada = datetime.fromtimestamp(timestamp) if timestamp else datetime.today()
        fecha_formateada = fecha_llamada.strftime("%Y-%m-%d %H:%M:%S")
        
        numero_crudo = llamada.get("raw_digits", "SinNumero")
        numero_cliente = re.sub(r'\D', '', str(numero_crudo)) or "SinNumero"
        
        usuario_obj = llamada.get("user")
        nombre_usuario = usuario_obj.get("name", "SinAgente") if usuario_obj and isinstance(usuario_obj, dict) else "SinAgente"
        nombre_usuario_limpio = limpiar_nombre_archivo(nombre_usuario)
        
        nombre_archivo = f"{numero_cliente}-{nombre_usuario_limpio}.mp3"
        
        linea_obj = llamada.get("number", {})
        linea_destino = linea_obj.get("name", "Sin Línea") if isinstance(linea_obj, dict) else "Sin Línea"
        
        registro = {
            "ID Call": llamada.get("id"),
            "Dirección": llamada.get("direction"),
            "Estado": llamada.get("status"),
            "Motivo Pérdida": llamada.get("missed_call_reason") or "N/A",
            "Fecha / Hora Inicio": fecha_formateada,
            "Duración (Seg)": llamada.get("duration", 0),
            "Teléfono Cliente": numero_crudo,
            "Línea Destino": linea_destino,
            "Agente Asignado": nombre_usuario,
            "Tags (Etiquetas)": ", ".join(tags_llamada) if tags_llamada else "Sin Tags",
            "País": llamada.get("country_code_a2", "N/A"),
            "url_audio": url_audio,
            "nombre_archivo_descarga": nombre_archivo
        }
        llamadas_procesadas.append(registro)
        
    return llamadas_procesadas

# --- Petición a la API de Aircall ---
def obtener_llamadas(desde, hasta):
    todas_las_llamadas = []
    url_actual = BASE_URL
    params = {"from": desde, "to": hasta, "order": "desc", "per_page": 50}
    
    while url_actual:
        try:
            if url_actual == BASE_URL:
                response = requests.get(url_actual, auth=HTTPBasicAuth(API_ID, API_TOKEN), params=params)
            else:
                response = requests.get(url_actual, auth=HTTPBasicAuth(API_ID, API_TOKEN))
                
            if response.status_code == 200:
                data = response.json()
                todas_las_llamadas.extend(data.get("calls", []))
                url_actual = data.get("meta", {}).get("next_page_link")
            else:
                st.error(f"Error de API: {response.status_code}")
                break
        except Exception as e:
            st.error(f"Error de conexión: {e}")
            break
            
    return todas_las_llamadas

# --- Interfaz en Barra Lateral ---
st.sidebar.header("Filtros de Búsqueda")
fecha_seleccionada = st.sidebar.date_input("Selecciona una fecha", datetime.today())

inicio_dia = int(time.mktime(fecha_seleccionada.timetuple()))
fin_dia = inicio_dia + 86399

# --- Disparador del Botón de Búsqueda ---
if st.sidebar.button("🔍 Filtrar y Tabular Llamadas"):
    with st.spinner("Buscando registros en Aircall..."):
        llamadas = obtener_llamadas(inicio_dia, fin_dia)
    
    if llamadas:
        st.session_state.datos_tabla = procesar_llamadas_para_tabla(llamadas)
        st.session_state.fecha_buscada = fecha_seleccionada
    else:
        st.session_state.datos_tabla = []
        st.sidebar.warning(f"⚠️ No se encontraron llamadas para el día {fecha_seleccionada}.")

# --- RENDERIZADO PERSISTENTE DE LA TABLA ---
if st.session_state.datos_tabla:
    st.write(f"### 📅 Resultados para el día: {st.session_state.fecha_buscada}")
    
    cantidad_llamadas = len(st.session_state.datos_tabla)
    st.metric(label="Cantidad de llamadas encontradas (Ventas)", value=cantidad_llamadas)
    st.markdown("---")
    
    cols_header = st.columns([1.2, 0.9, 0.9, 1.2, 1.6, 0.8, 1.3, 1.5, 1.3, 1.6, 0.5, 2.5, 1.2])
    titulos = ["ID Call", "Dirección", "Estado", "Motivo", "Fecha Inicio", "Duración", "Tel. Cliente", "Línea Destino", "Agente", "Tags", "País", "Reproductor", "Acción"]
    
    for col, tit in zip(cols_header, titulos):
        col.markdown(f"**{tit}**")
    st.markdown("---")
    
    for item in st.session_state.datos_tabla:
        cols_fila = st.columns([1.2, 0.9, 0.9, 1.2, 1.6, 0.8, 1.3, 1.5, 1.3, 1.6, 0.5, 2.5, 1.2])
        
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
        
        # Reproductor de audio
        with cols_fila[11]:
            st.audio(item["url_audio"], format="audio/mp3")
        
        # Botón de descarga
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
                    key=f"dl_{item['ID Call']}"
                )
            except Exception:
                st.error("Error")

elif st.session_state.datos_tabla == []:
    st.info("ℹ️ No hay llamadas con los tags específicos para la fecha seleccionada.")