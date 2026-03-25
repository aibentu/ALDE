plan to refactor:

1.  - die gesamte modell / agent / tool configuration, parametrisierung  soll   in die agents_config umziehen. 

 -  unter einem agent_label soll die gesamte configuration und parametrisierung geschrieben werden. 
 - REGESTRIERUNG der tools weiterhin in tools.py 
 - REGESTRIERUNG der agents weiterhin in agents_registry.py 
 - die agents_config.py soll die zentrale konfigurationsdatei für alle agenten und tools werden. 
 - die agenten und tools sollen weiterhin in ihren jeweiligen modulen registriert werden, aber die konfiguration und parametrisierung soll zentral in der agents_config.py erfolgen. 
 -  die agents_config.py soll eine klare struktur haben, um die konfiguration der agenten und tools übersichtlich zu gestalten. 
 -  die agents_config.py soll auch die möglichkeit bieten, verschiedene konfigurationen für verschiedene anwendungsfälle oder workflows zu definieren. 
 -  die agents_config.py soll leicht erweiterbar sein, um neue agenten oder tools hinzuzufügen oder bestehende zu modifizieren.


2.  - definition von deterministischen agent/tool chains/workflows wird in der agents_config möglich sein. 

die agents_registry wird instanziiert, agenten werden über ihre definierten lables registriert. tools werden ebenfalls mit ihren konfigurationen aus der agents_config registriert.
die agents und tools werden iterativ aufgerufen und ausgefuehrt, basierend auf den definierten workflows in der agents_config. die agents_config definiert die reihenfolge und die abhängigkeiten der agenten und tools, um komplexe workflows zu ermöglichen. die agents_registry dient als zentrale stelle, um agenten und tools zu verwalten und zu orchestrieren, während die agents_config die details der konfiguration und parametrisierung enthält.

3.  - deterministischer workflow: sequenz and state definition //
logik für die ausführung der agenten und tools basierend auf der definierten sequenz und dem aktuellen state. die agents_config definiert die sequenz der agenten und tools, sowie die möglichen states und transitions. die agents_registry orchestriert die ausführung basierend auf dieser definition, um sicherzustellen, dass die agenten und tools in der richtigen reihenfolge und unter den richtigen bedingungen ausgeführt werden. dies ermöglicht komplexe workflows, bei denen die ausführung von agenten und tools von vorherigen ergebnissen oder bestimmten zuständen abhängen kann.




4.  - die agents_config soll auch die möglichkeit bieten, verschiedene konfigurationen für verschiedene anwendungsfälle oder workflows zu definieren. dies ermöglicht es, spezifische agenten und tools für bestimmte aufgaben oder projekte zu konfigurieren, ohne die allgemeine konfiguration zu beeinflussen. die agents_config kann verschiedene sektionen oder profiles enthalten, die jeweils eine eigene konfiguration für agenten und tools definieren, um flexibel auf unterschiedliche anforderungen reagieren zu können.

5. - Ziel ist eine Flexible Architektur/Konfigurations engine die alle logischen muster erlaubt. / Fuer den Produktiv einsatz best Practices nutzt. / Weiteres Ziel ist das komplexe ablauefe /  Workflows / tasks geplant und persistent konfiguriert werden und mit eigener engine_instanz als service laufen ...  


6. - handhabung von handoffs zwichen agenten.
definieren von klaren schnittstellen und protokollen für die kommunikation und den datenaustausch zwischen agenten. die agents_config kann diese schnittstellen und protokolle definieren, um sicherzustellen, dass agenten effektiv zusammenarbeiten können. 

eg. agent_response = {
    "agent_label": "Agent A",
    "output": "Ergebnis von Agent A",  oder "generated": "...", oder "msg": "...",
    "handoff_to": "Agent B"
}  