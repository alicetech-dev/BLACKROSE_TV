#!/usr/bin/env python3
"""Genera segmentos/apagon.json: «EL APAGÓN MUNDIAL QUE NO FUE», informe especial de BlackRose TV (18-nov-2026).
Investigado, redactado y diseñado por IA con notas reales (ADN Radio / EFE Verifica, The Clinic, Computerworld, Xataka, Infobae, MDZ, WIRED).
Cada dato sale de lo que dicen esas notas (ver apagon_fuentes.md); lo que es criterio propio de BlackRose se dice como tal.
    cd ~/joy_vmc && .venv/bin/python director/segmentos/apagon.py
Campos de cada slide: etiqueta, titulo, sub, foto{img,dominio,fuente,alto}, bullets[], cifras[{n,l}], linea[{t,l}], sello{texto,color}, fuentes, habla[{quien,texto}]"""
import json, os

IMG = "/segmento/img/"
foto = lambda f, dom, fuente, alto=300: {"img": IMG + f, "dominio": dom, "fuente": fuente, "alto": alto}

SLIDES = [
 dict(id="portada", etiqueta="INFORME ESPECIAL", titulo="EL APAGÓN MUNDIAL QUE NO FUE", sub="rumor · fallas · hackeos: qué pasó de verdad",
      bullets=["Investigado, escrito y presentado por inteligencia artificial", "Fuentes reales, citadas una por una", "Martes 17 de noviembre de 2026"],
      habla=[dict(quien="joy", texto="Buenas noches. Esto es un informe especial de BlackRose TV, y viene con una diferencia: este segmento lo investigó, lo escribió y lo presenta una inteligencia artificial. "
            "Todo con fuentes reales, citadas una por una. El tema: el supuesto apagón mundial que se anunció para el martes diecisiete de noviembre. ¿Qué pasó de verdad? Vamos a verlo.")]),

 dict(id="rumor", etiqueta="1 · EL RUMOR", titulo="72 HORAS SIN LUZ, INTERNET NI BANCOS", foto=foto("rumor_adn.jpg", "adnradio.cl", "ADN Radio · 17 nov 2026"),
      bullets=["Circuló en TikTok, Facebook y X", "Prometía cortes de electricidad, internet y bancos", "Sin pruebas ni advertencias oficiales"],
      habla=[dict(quien="kuroki", texto="Empecemos por el rumor. Durante semanas, publicaciones en TikTok, Facebook y X advirtieron de un apagón mundial de setenta y dos horas: sin electricidad, sin internet y sin servicios bancarios. "
            "Según ADN Radio, no existían pruebas ni advertencias oficiales que respaldaran esas afirmaciones.")]),

 dict(id="origen", etiqueta="2 · DE DÓNDE SALIÓ", titulo="UNA PRUEBA REAL… DE ALERTAS EN EE. UU.", foto=foto("rumor_clinic.jpg", "theclinic.cl", "The Clinic · 16 nov 2026", 250),
      cifras=[dict(n="16:20", l="hora de Chile"), dict(n="14:20", l="hora este de EE. UU."), dict(n="≈ 1 min", l="duración")],
      bullets=["FEMA y la FCC probaron el Sistema de Alertas de Emergencia", "Interrumpe radio y TV de EE. UU.; no celulares, luz ni bancos"],
      habla=[dict(quien="joy", texto="¿De dónde salió entonces? De algo real, pero mucho más pequeño. Según EFE Verifica, citado por ADN Radio, ese día la agencia FEMA y la FCC programaron una prueba nacional del Sistema de Alertas de Emergencia de Estados Unidos: "
            "a las dos y veinte de la tarde, hora del este, las cuatro y veinte en Chile. Dura aproximadamente un minuto, interrumpe radio y televisión estadounidenses, y no afecta celulares, electricidad ni servicios bancarios.")]),

 dict(id="veredicto", etiqueta="3 · VEREDICTO", titulo="EL APAGÓN GLOBAL: SIN RESPALDO", sello=dict(texto="RUMOR SIN RESPALDO", color="#ff3b3b"),
      bullets=["Ningún organismo científico, gubernamental ni eléctrico emitió alerta (The Clinic)", "Mezcla una prueba real con supuestos documentos filtrados sin respaldo", "También se lo vinculó a un capítulo de Los Simpson de 2023"],
      habla=[dict(quien="kuroki", texto="Veredicto sobre el rumor: sin respaldo. The Clinic recuerda que ningún organismo científico, gubernamental ni eléctrico emitió alerta alguna de desconexión global. "
            "El rumor mezcla una prueba real con supuestos documentos filtrados que nadie pudo verificar, y hasta se colgó de un capítulo de Los Simpson de dos mil veintitrés. Mucha estética de noticia de última hora; cero evidencia.")]),

 dict(id="microsoft", etiqueta="4 · PERO SÍ HUBO FALLAS", titulo="MICROSOFT: CASI 24 HORAS CAÍDO", foto=foto("msft_cw.jpg", "computerworld.es", "Computerworld · 17 nov 2026", 200),
      linea=[dict(t="JULIO", l="se despliega una actualización con un defecto latente"), dict(t="+ 3 MESES", l="funciona en todo el mundo sin incidentes"),
             dict(t="JUE 12 NOV", l="una sobrecarga activa el defecto: caen Outlook, Teams y Copilot"), dict(t="≈ 24 H", l="servicio inestable"), dict(t="LUN 16", l="Microsoft publica su informe preliminar")],
      habla=[dict(quien="joy", texto="Ahora, lo que sí pasó. La semana pasada, Microsoft estuvo casi un día con Outlook caído, y Teams y Copilot a medias. Según Computerworld, la causa fue una actualización desplegada en julio que traía un defecto latente: "
            "durante más de tres meses funcionó en todo el mundo sin problemas, hasta que una sobrecarga de tráfico lo activó. Y Microsoft reconoce que su entorno de pruebas no se parecía a la infraestructura real. La explicación de la empresa es un error latente y una sobrecarga, no un ataque.")]),

 dict(id="racha", etiqueta="5 · LA RACHA", titulo="UNA SEMANA DE FALLAS EN CADENA", foto=foto("apple_infobae.jpg", "infobae.com", "Infobae · 17 nov 2026", 190),
      bullets=["Microsoft Exchange: miles de empresas sin servicios", "FAA: un fallo técnico dejó aviones en tierra", "JPMorgan Chase: problema de software", "United Airlines: falla de sistema, vuelos retrasados",
               "NSA: red clasificada fuera de servicio", "Apple: iCloud, Apple Pay y App Store (+2.300 reportes)"],
      habla=[dict(quien="kuroki", texto="La racha impresiona. En cuatro días hábiles seguidos, según WIRED: una caída masiva de Microsoft Exchange, un fallo de la Administración Federal de Aviación que dejó aviones en tierra, un problema de software en JPMorgan Chase, "
            "fallas en United Airlines y una red clasificada de la NSA fuera de servicio. Y el martes, Apple: iCloud, Apple Pay y App Store, con más de dos mil trescientos reportes en Down Detector solo para Apple Pay, según Infobae.")]),

 dict(id="conexion", etiqueta="6 · ¿LAS UNE ALGO?", titulo="¿ATAQUE COORDINADO?", foto=foto("wired.jpg", "es.wired.com", "WIRED · 18 nov 2026", 190), sello=dict(texto="SIN PRUEBAS DE CONEXIÓN", color="#ffb627"),
      bullets=["No hay pruebas de que los fallos estén relacionados", "Ni de que los provocaran hackers", "La mayoría de las caídas no son maliciosas: son sistemas colapsando por su complejidad"],
      habla=[dict(quien="joy", texto="¿Las une algo? WIRED lo investigó y su conclusión, de este miércoles, es clara: todavía no hay pruebas de que estos fallos estuvieran relacionados, y mucho menos de que los causaran hackers. "
            "La gran mayoría de las caídas digitales no nacen de una intención maliciosa, sino de administradores luchando para que sistemas cada vez más complejos no colapsen bajo su propio peso.")]),

 dict(id="hackeo", etiqueta="7 · EL HACKEO REAL", titulo="178 ORGANIZACIONES, UN PROVEEDOR", foto=foto("hack_mdz.jpg", "mdzol.com", "MDZ · 17 nov 2026", 170),
      cifras=[dict(n="178", l="organizaciones"), dict(n="188", l="scripts infectados"), dict(n="1.611", l="archivos analizados")],
      bullets=["Falla en Optimizely, plataforma de pruebas web", "Entre los sitios: CNN, BBC, Fox News, NPR", "Buscaba datos de tarjetas y desviar criptomonedas", "No implica hackeo directo a cada medio"],
      habla=[dict(quien="kuroki", texto="Y ahora, un ataque que sí fue real. Según MDZ, investigadores de Report URI encontraron código malicioso en servicios de Optimizely, una plataforma de pruebas para páginas web: ciento ochenta y ocho scripts infectados que alcanzaron a ciento setenta y ocho organizaciones, "
            "entre ellas CNN, BBC y Fox News. El código buscaba robar datos de tarjetas y desviar criptomonedas. Ojo: eso no significa que hackearan a cada medio ni que todos sus visitantes perdieran datos, y Optimizely dice que ya corrigió la vulnerabilidad. Coincidió en fechas, pero ninguna de las fuentes que revisamos lo vincula con las caídas.")]),

 dict(id="distinguir", etiqueta="8 · CÓMO DISTINGUIR", titulo="RUMOR · FALLA · CIBERATAQUE", sub="criterio BlackRose (IA), no de las fuentes",
      linea=[dict(t="RUMOR", l="fecha y hora exactas + «filtración» sin fuente = sospecha"), dict(t="FALLA", l="la propia empresa explica la causa técnica (como Microsoft)"),
             dict(t="CIBERATAQUE", l="investigadores con evidencia técnica y un proveedor afectado (como Optimizely)")],
      habla=[dict(quien="joy", texto="Entonces, ¿cómo distinguir? Una regla práctica nuestra, no de las fuentes. Un rumor trae fecha y hora exactas y una supuesta filtración sin respaldo. Una falla técnica la explica la propia empresa, como hizo Microsoft. "
            "Y un ciberataque lo documentan investigadores con evidencia técnica, como en el caso de Optimizely.")]),

 dict(id="consejos", etiqueta="9 · QUÉ HACER", titulo="PREPÁRATE SIN PÁNICO", sub="consejos BlackRose",
      bullets=["Copias de seguridad de lo que importa", "No dependas de un solo servicio", "Contraseñas únicas y verificación en dos pasos", "Desconfía de alertas virales con hora exacta", "Contrasta con medios y fuentes oficiales"],
      habla=[dict(quien="kuroki", texto="Qué hacer. Primero: copias de seguridad de lo que de verdad importa. Segundo: no dependas de un solo servicio. Tercero: contraseñas únicas y verificación en dos pasos. "
            "Y cuarto, el más útil de todos: desconfía de cualquier alerta viral con hora exacta, y contrástala con medios y fuentes oficiales antes de compartirla.")]),

 dict(id="resumen", etiqueta="RESUMEN", titulo="LO QUE PASÓ DE VERDAD", fuentes="ADN Radio (EFE Verifica) · The Clinic · Computerworld · Xataka · Infobae · MDZ · WIRED",
      bullets=["Apagón mundial: rumor sin respaldo", "Caídas: reales, con explicaciones técnicas", "Hackeo a proveedor web: real, aparte", "Conexión entre todo: sin pruebas"],
      habla=[dict(quien="joy", texto="En resumen: el apagón mundial fue un rumor sin respaldo; las caídas fueron reales y tienen explicaciones técnicas; el hackeo a proveedores web también fue real, y hasta ahora nada prueba que todo esté conectado. "
            "Este informe fue investigado, redactado y diseñado por inteligencia artificial, con fuentes reales. Revisa siempre las notas originales."),
             dict(quien="kuroki", texto="Gracias por acompañarnos. Esto fue un informe especial de BlackRose TV, tu fuente de información tecnológica.")]),
]

if __name__ == "__main__":
    out = dict(id="apagon", titulo="EL APAGÓN MUNDIAL QUE NO FUE", slides=SLIDES)
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "apagon.json"), "w"), ensure_ascii=False, indent=1)
    print(len(SLIDES), "slides ·", sum(len(h["texto"].split()) for s in SLIDES for h in s["habla"]), "palabras narradas")
