# Donald Trump rejects Iran's response to US peace proposal as unacceptable

**Configuration:** T = 0.55, V = V2  
**Date:** 2026-05-11 · bundle topic-01  
**Slug:** borderline-trump-iran-peace

## Topic

> Donald Trump has dismissed Iran's counter-terms for ending the regional conflict, leading to a sharp rise in global oil prices and volatility in international stock markets. Iranian officials have warned of new attacks while describing US demands as unreasonable, as coverage across Western and Middle Eastern media highlights the breakdown in negotiations.

- Original `source_count` (production, T=0.30 V1): **144**
- Audit labels: on = **71**, off = **73**, total = **144**, baseline off % = **50.7%**

## At this configuration (T = 0.55, V = V2)

- Retained (sim ≥ 0.55): **36** of 144
- Dropped: **108**
- On-topic retained: **34** / 71 (recall = **0.479**)
- Off-topic retained: **2** (off % of retained = **5.6%**, precision = **0.944**)

## Findings

Sorted by similarity descending. **Kept** = sim ≥ threshold (assigned at this config). **Drop** = sim < threshold (would orphan or move to another topic). The audit `label` and `reasoning_note` are unchanged across configs — they describe the finding, not the cut.

| # | sim | kept | label | lang | outlet | title | reasoning |
|---:|---:|:--:|:--:|:--|:--|:--|:--|
| 1 | 0.919 | yes | on | en | Japan Today | Trump calls Iran's response to U.S. peace proposal 'unacceptable' | Trump calls Iran's response to US peace proposal unacceptable — direct |
| 2 | 0.889 | yes | on | ru | Meduza | Трамп назвал ответ Ирана на мирное предложение Вашингтона «неприемлемым» | Трамп ответ Ирана мирное предложение неприемлемым — direct |
| 3 | 0.878 | yes | on | de | Tagesschau | Nach US-Vorschlag: Trump findet Irans Antwort "völlig inakzeptabel" | Trump findet Irans Antwort völlig inakzeptabel US-Vorschlag — direct |
| 4 | 0.856 | yes | on | en | NPR | Trump rejects Iran's latest response to U.S. ceasefire proposal | Trump rejects Iran's latest response US ceasefire proposal Pakistani — direct |
| 5 | 0.852 | yes | on | en | Guardian World | Trump calls Iran’s response to peace plan ‘totally unacceptable’ as ceasefire frays | Trump calls Iran totally unacceptable ceasefire frays drones Gulf — direct |
| 6 | 0.851 | yes | on | en | South China Morning Post | Trump calls Iran’s response to US peace proposal ‘unacceptable’ | Trump calls Iran's response to US peace proposal unacceptable — direct |
| 7 | 0.844 | yes | on | en | RT | Iran’s response to US peace terms ‘totally unacceptable’ – Trump | Iran's response to US peace terms totally unacceptable Trump RT — direct |
| 8 | 0.840 | yes | on | en | DW News | Iran war: Trump rejects proposal to end conflict | Iran war Trump rejects proposal end conflict totally unacceptable — direct |
| 9 | 0.834 | yes | on | en | Guardian World | Middle East crisis live: Trump rejects Iran response to US peace proposal as Tehran warns  | Middle East crisis Trump rejects Iran response Tehran retaliate — direct |
| 10 | 0.824 | yes | on | en | Vanguard Nigeria | Trump rejects Iran peace terms as Tehran warns of new attacks | Trump rejects Iran peace terms Tehran warns new attacks — direct |
| 11 | 0.812 | yes | on | en | BBC World | Trump calls Iran response to US proposal to end war 'totally unacceptable' | Trump calls Iran response US proposal end war totally unacceptable Hormuz — direct |
| 12 | 0.809 | yes | on | en | Al Jazeera | Trump calls Iran response “totally unacceptable” | Trump calls Iran response totally unacceptable — direct |
| 13 | 0.803 | yes | on | de | Tagesschau | ++ Trump: Antwort aus Iran "völlig inakzeptabel"  ++ | Trump Antwort aus Iran völlig inakzeptabel Netanyahu — direct |
| 14 | 0.794 | yes | on | en | Anadolu Agency | Trump rebuffs Iranian response to latest US proposal to end war | Trump rebuffs Iranian response latest US proposal end war — direct |
| 15 | 0.788 | yes | off | en | NPR | Morning news brief | NPR morning brief multi-topic Trump heads China amid Iran war |
| 16 | 0.754 | yes | on | es | El Pais | Trump considera “totalmente inaceptable” la respuesta de Irán a su propuesta de paz | Trump considera totalmente inaceptable respuesta Irán sanciones Ormuz — direct |
| 17 | 0.725 | yes | on | en | Dawn | Trump rejects ‘unacceptable’ Iranian terms for ending war | Trump rejects unacceptable Iranian terms ending war Pakistani — direct |
| 18 | 0.722 | yes | on | en | Axios | Trump to Axios: "I don't like" Iran's peace plan response | Trump to Axios I don't like Iran peace plan response — direct |
| 19 | 0.716 | yes | on | en | Le Monde | Trump says Iran response to US ceasefire proposal 'totally unacceptable' | Trump Iran totally unacceptable French-British Hormuz operation — direct |
| 20 | 0.711 | yes | on | en | Dawn | Iran says made 'legitimate' demands in peace proposal rejected by Trump as 'totally unacce | Iran legitimate demands peace proposal rejected Trump totally — direct |
| 21 | 0.710 | yes | on | fr | RFI | EN DIRECT - Guerre au Moyen-Orient: les États-Unis continuent d’avoir des «exigences dérai | Guerre Moyen-Orient EE.UU. exigences déraisonnables Trump Iran — direct |
| 22 | 0.710 | yes | on | es | El Financiero | ‘La guerra sigue’: Trump e Irán rechazan sus propuestas de paz para poner fin al conflicto | La guerra sigue Trump Irán rechazan propuestas paz — direct |
| 23 | 0.692 | yes | on | en | Press TV | Yemen’s Ansarullah warns US after Trump rejected Iran’s proposal | Yemen Ansarullah warns US after Trump rejected Iran's proposal — direct |
| 24 | 0.686 | yes | on | pt | Agencia Brasil | Irã envia resposta à proposta de paz dos EUA | Irã envia resposta a proposta de paz dos EUA — direct |
| 25 | 0.678 | yes | off | en | Middle East Eye | Morning update | MEE Morning update multi-topic newsletter |
| 26 | 0.669 | yes | on | es | Infobae | Irán no cede en las negociaciones con EE.UU. y trata de imponer sus exigencia a Trump | Irán no cede negociaciones EE.UU. imponer exigencias Trump — direct |
| 27 | 0.656 | yes | on | de | Tagesschau | Iran übermittelt Antwort auf US-Vorschlag über neue Verhandlungen | Iran übermittelt Antwort US-Vorschlag 14-Punkte Verhandlungen — direct |
| 28 | 0.643 | yes | on | en | Al Jazeera | Iran says US making ‘unreasonable’ demands in negotiations to end war | Iran says US making unreasonable demands negotiations end war Baghaei — direct |
| 29 | 0.640 | yes | on | de | Tagesschau | Iran-Liveblog: ++ Iran wehrt sich gegen Kritik von Trump ++ | Iran wehrt sich gegen Kritik Trump Vorschlag legitim großzügig — direct |
| 30 | 0.623 | yes | on | en | Press TV | Trump's deadly trap: By rejecting Iran's proposal, US enters a strategic nightmare with no | Trump's deadly trap rejecting Iran's proposal strategic nightmare — direct |
| 31 | 0.605 | yes | on | en | Financial Times | Trump says Iran’s response to peace proposal ‘unacceptable’ | Trump says Iran's response peace proposal unacceptable oil — direct |
| 32 | 0.597 | yes | on | en | CNA | Iran describes its proposal to end war with US as 'legitimate' | Iran describes proposal end war US legitimate naval blockade — direct |
| 33 | 0.578 | yes | on | en | Middle East Eye | Iran describes its proposal to end war with US as 'legitimate' and 'generous' | Iran describes proposal to end war with US legitimate generous — direct |
| 34 | 0.576 | yes | on | en | Press TV | Iran says its proposal was generous as US insists on ‘unreasonable demands’ | Iran says proposal generous US insists unreasonable demands — direct |
| 35 | 0.570 | yes | on | en | South China Morning Post | Trump, Tehran and a Qatari tanker transit: here’s what happened overnight | Trump Tehran Qatari tanker transit overnight 10th week — direct |
| 36 | 0.559 | yes | on | pt | Folha de S.Paulo | Petr�leo abre em alta ap�s Trump classificar proposta iraniana como inaceit�vel | Petróleo Trump iraniana inaceitável abre alta — direct |
| 37 | 0.534 | no | on | en | Middle East Eye | Iran demands sovereignty over Hormuz in counterproposal to US | Iran demands sovereignty over Hormuz in counterproposal to US — direct |
| 38 | 0.534 | no | on | es | El Financiero | ‘Ya no se reirán más’: Trump arremete contra Irán, Barak Obama y Joe Biden | Ya no se reirán más Trump arremete contra Irán Obama Biden — direct |
| 39 | 0.533 | no | on | en | Press TV | Iran peace plan demands war compensation, sovereignty over Hormuz | Iran peace plan demands war compensation sovereignty Hormuz — direct |
| 40 | 0.517 | no | on | en | Vanguard Nigeria | Iran demands end to war, release of frozen assets in response to US | Iran demands end to war release frozen assets in response to US — direct |
| 41 | 0.516 | no | on | en | Responsible Statecraft | If Trump wants out of war he needs to stand up to Israel on Lebanon | If Trump wants out of war he needs to stand up Israel Lebanon — direct |
| 42 | 0.509 | no | on | en | Al Jazeera | Iran war day 73: Trump and Tehran clash over latest peace proposals | Iran war day 73 Trump Tehran clash latest peace proposals — direct |
| 43 | 0.509 | no | off | en | Middle East Eye | Netanyahu hints at US troop deployment against Iran in CBS interview | Netanyahu hints at US troop deployment against Iran CBS |
| 44 | 0.475 | no | on | en | Press TV | China rejects illegal US sanctions over Iran, vows to protect firms | China rejects illegal US sanctions over Iran vows protect firms — direct |
| 45 | 0.475 | no | on | en | Anadolu Agency | Trump to 'pressure' Xi over Iran support during visit, says White House official | Trump to pressure Xi over Iran support during visit White House — direct |
| 46 | 0.455 | no | on | en | Press TV | US suffers 'total defeat' in war against Iran, faces irreversible strategic collapse: Neoc | US suffers total defeat war against Iran Kagan strategic collapse — direct |
| 47 | 0.450 | no | off | es | El Pais | Los chinos hablan sobre la visita de Trump: “No le doy la bienvenida porque ha iniciado gu | Chinos hablan visita Trump bienvenida recelo Pekín |
| 48 | 0.449 | no | on | en | RT | Trump vows to get Iran’s enriched uranium | Trump vows to get Iran's enriched uranium stockpile — direct |
| 49 | 0.448 | no | off | en | RT | Iran’s new ‘atomic bomb’: How US policy pushed Iran over the brink | Iran's new atomic bomb US policy pushed brink column |
| 50 | 0.441 | no | off | en | Kyiv Independent | Ukraine to 'respond in kind' if Russia refrains from mass aerial attacks, Zelensky says | Ukraine respond in kind if Russia refrains mass aerial |
| 51 | 0.435 | no | on | en | NDTV | Iran War Could Make Trump's Trip To China A Bit Chillier Than His Last Visit | Iran War could make Trump's trip to China chillier — direct |
| 52 | 0.435 | no | on | en | Financial Times | Trump to press China’s Xi about Iran war at summit | Trump to press China's Xi about Iran war at summit — direct |
| 53 | 0.410 | no | on | en | Anadolu Agency | Trump says 'we'll blow them up' if Iran uranium site accessed | Trump 'we'll blow them up' if Iran uranium site accessed — direct |
| 54 | 0.409 | no | on | en | Anadolu Agency | Qatar, Saudi Arabia discuss de-escalation efforts amid US-Iran conflict | Qatar Saudi Arabia de-escalation efforts amid US-Iran conflict — direct |
| 55 | 0.406 | no | off | pt | Folha de S.Paulo | Apoio republicano a Trump n�o � incondicional, e ele pode cavar sua pr�pria cova, diz espe | Apoio republicano Trump não incondicional cavar cova |
| 56 | 0.396 | no | on | en | NDTV | Opinion: Opinion \| What's Behind Araghchi's Visit To China Right Before Trump-Xi Meeting? | Araghchi visit China before Trump-Xi meeting Iran war — direct |
| 57 | 0.393 | no | off | es | El Financiero | ‘Si vamos, deben aceptar’: Estas son las condiciones de Irán para jugar el Mundial 2026 en | Iran condiciones FIFA Mundial 2026 jugar |
| 58 | 0.392 | no | on | es | Infobae | Xi y Trump medirán este jueves en Pekín sus diferencias, con Irán y los aranceles de fondo | Xi y Trump Pekín Irán y aranceles diferencias — direct Iran focus |
| 59 | 0.392 | no | on | en | RT | Maximum pressure, minimum victory: How the US lost the momentum in Iran | Maximum pressure minimum victory US lost momentum in Iran — direct |
| 60 | 0.391 | no | off | en | Middle East Eye | Iran says US has not issued World Cup visas for players | Iran says US has not issued World Cup visas players |
| 61 | 0.383 | no | off | es | El Financiero | Visita incómoda de Trump a China: Los temas que tensan la reunión con Xi Jinping | Visita incómoda Trump China temas Xi |
| 62 | 0.379 | no | on | en | Anadolu Agency | Iran war ‘not over’ until enriched uranium removed: Netanyahu | Iran war not over until enriched uranium removed Netanyahu — direct |
| 63 | 0.374 | no | off | en | Middle East Eye | Hegseth rejects senator’s claims US munitions are depleted | Hegseth rejects senator claims US munitions are depleted |
| 64 | 0.373 | no | off | en | South China Morning Post | Ukraine and Russia accuse each other of breaking US-brokered ceasefire | Ukraine and Russia accuse each other breaking US-brokered ceasefire |
| 65 | 0.373 | no | off | en | RT | US might move its troops from Germany to another EU nation – Trump | US move troops Germany to Poland Trump |
| 66 | 0.370 | no | on | en | Al Jazeera | Former Qatar PM: Netanyahu using Iran war to reshape Middle East | Former Qatar PM Netanyahu Iran war reshape Middle East Hormuz Gulf NATO — direct |
| 67 | 0.365 | no | off | en | Kyiv Independent | Ukraine gives Russia POW exchange list, seeks US guarantees for deal, Zelensky says | Ukraine POW exchange list US guarantees Zelensky |
| 68 | 0.364 | no | off | en | Anadolu Agency | Azerbaijani leader slams EU border observers, saying they act ‘as if they are defending Ar | Azerbaijani Aliyev EU border observers Armenia |
| 69 | 0.359 | no | off | en | Yonhap | Main opposition slams gov't for not identifying Iran behind attack on S. Korean vessel | SK opposition slams gov't not identifying Iran SK vessel duplicate |
| 70 | 0.358 | no | on | fr | RFI | Conflit Iran–États-Unis–Israël: comment l’Arabie saoudite tente de se tenir à distance de  | Arabie saoudite tenir distance Iran-USA-Israël conflit positionnement — direct context |
| 71 | 0.357 | no | on | en | BBC World | Oil prices jump after Trump dismisses Iran proposal to end war | Oil prices jump after Trump dismisses Iran proposal end war — direct |
| 72 | 0.356 | no | on | es | El Financiero | Trump le copia el plan a México: Analiza bajar impuestos a combustibles para evitar un gas | Trump copia plan México analiza bajar impuestos combustibles evitar — direct US gas response to Iran oil |
| 73 | 0.355 | no | on | tr | Hurriyet | Hizbullah'tan İsrail ordusuna misilleme: 40 ülke Hürmüz'e askeri müdahaleyi görüşecek | Hizbullah İsrail 40 ülke Hürmüz askeri müdahale — direct multinational Hormuz |
| 74 | 0.352 | no | off | en | Yonhap | (LEAD) Main opposition slams gov't for not identifying Iran behind attack on S. Korean ves | SK main opposition slams gov't not identifying Iran SK vessel |
| 75 | 0.347 | no | on | tr | Hurriyet | Trump ve Hamaney’in ortak noktaları neler? Dünyayı krize sokan inat! | Trump ve Hamaney ortak noktaları dünyayı krize sokan inat — direct |
| 76 | 0.346 | no | off | en | Al Jazeera | Is the Vatican standing up to Trump? | Vatican standing up to Trump Kim Daniels Tlhabi |
| 77 | 0.342 | no | off | en | Yonhap | (2nd LD) Main opposition slams gov't for not identifying Iran behind attack on S. Korean v | SK opposition slams gov't Iran SK vessel duplicate |
| 78 | 0.339 | no | off | en | BBC World | Trump's China visit set to test fragile truce | Trump's China visit set to test fragile tariff truce |
| 79 | 0.338 | no | off | en | Al Jazeera | Russia and Ukraine accuse the other of ceasefire violations | Russia and Ukraine accuse other ceasefire violations |
| 80 | 0.335 | no | on | en | Anadolu Agency | Iran says presence of French, British ships in Hormuz will be met with ‘decisive, immediat | Iran French British ships Hormuz decisive immediate response — direct |
| 81 | 0.331 | no | on | en | Anadolu Agency | Turkish, Egyptian foreign ministers discuss Iran-US negotiations in phone call | Turkish Egyptian foreign ministers discuss Iran-US negotiations — direct |
| 82 | 0.330 | no | off | en | Press TV | Iranian air defense downs hostile drone in southwest, Army says | Iranian air defense downs hostile drone southwest |
| 83 | 0.326 | no | on | en | Responsible Statecraft | Taiwan is looming over this week's Trump and Xi summit | Taiwan looming over this week's Trump and Xi summit Iran war — direct |
| 84 | 0.325 | no | off | en | Eurasianet | Armenia thumbs nose at Kremlin as it receives strong EU endorsement | Armenia thumbs nose Kremlin EU endorsement |
| 85 | 0.324 | no | off | en | Press TV | Macron: France 'never considered' military deployment unccordinated with Iran | Macron France never considered military Hormuz Iran |
| 86 | 0.320 | no | off | en | Japan Today | Russia and Ukraine accuse each other of violating 3-day truce | Russia Ukraine accuse each other violating 3-day truce |
| 87 | 0.320 | no | off | pt | Folha de S.Paulo | EUA criticam Taiwan por atrasar recursos de defesa diante de amea�a da China | EUA Taiwan defesa China |
| 88 | 0.319 | no | off | en | Al Jazeera | Ex-Israeli PM: Hezbollah is the enemy of Lebanon and must be disarmed | Ex-Israeli PM Olmert Hezbollah Lebanon 2006 war disarm |
| 89 | 0.319 | no | on | en | Dawn | Oil rises $4 after Trump rejects Iran's response to US peace proposal | Oil rises $4 after Trump rejects Iran response US peace proposal — direct |
| 90 | 0.318 | no | off | en | RT | Israel should end reliance on US cash – Netanyahu | Israel should end reliance on US cash Netanyahu zero |
| 91 | 0.318 | no | off | en | BBC World | Putin says he thinks Ukraine conflict 'coming to an end' | Putin Ukraine conflict coming to end backing Zelensky |
| 92 | 0.317 | no | off | es | Infobae | China se muestra dispuesta a lograr una "mayor estabilidad" global de cara al encuentro en | China dispuesta mayor estabilidad encuentro |
| 93 | 0.316 | no | off | en | Vanguard Nigeria | Iran hangs man accused of passing info to CIA, Mossad | Iran hangs man accused passing info CIA Mossad execution |
| 94 | 0.315 | no | off | en | Anadolu Agency | Zelenskyy says Ukraine pushed Putin 'a little' toward a potential meeting | Zelenskyy says Ukraine pushed Putin toward potential meeting |
| 95 | 0.313 | no | off | en | Ukrinform | Umerov discusses possible leader-level meeting formats in US to end war – Zelensky | Umerov leader-level meeting US end war Ukraine |
| 96 | 0.312 | no | off | en | NDTV | Iran Hangs Man Convicted Of Spying, Leaking Secrets To Mossad, US | Iran Hangs Man Convicted Spying Mossad US satellite |
| 97 | 0.311 | no | off | en | Eurasianet | Kazakhstan sticking with OPEC | Kazakhstan sticking with OPEC Kremlin |
| 98 | 0.310 | no | off | en | South China Morning Post | China readies for Trump visit amid rebound in trade growth | China readies Trump visit He Lifeng Bessent Seoul |
| 99 | 0.309 | no | off | en | South China Morning Post | China confirms dates for President Donald Trump’s state visit to Beijing | China confirms dates Trump state visit Beijing |
| 100 | 0.309 | no | on | en | Vanguard Nigeria | Oil prices rise as Trump rejects Iran’s terms | Oil prices rise as Trump rejects Iran's terms — direct |
| 101 | 0.303 | no | off | en | Middle East Eye | Iran executes man accused of spying for CIA and Mossad | Iran executes man accused of spying for CIA and Mossad |
| 102 | 0.302 | no | off | en | South China Morning Post | Trump’s China return: what’s changed since his ‘friendly’ 2017 visit | Trump China return changed since friendly 2017 visit |
| 103 | 0.296 | no | off | es | Infobae | Albares presiona a los Veintisiete para someter a voto la suspensión parcial del Acuerdo d | Albares Veintisiete suspensión Acuerdo Asociación |
| 104 | 0.296 | no | off | ru | Meduza | Война. 1537-й день. Украина и Россия обвиняют друг друга в нарушениях перемирия. Западные  | Война 1537-й день перемирия нарушения |
| 105 | 0.289 | no | off | en | BBC World | Iran activists tell BBC how threat of war intensifies trauma of repression | Iran activists BBC threat war intensifies trauma repression |
| 106 | 0.288 | no | off | en | RT | Moscow expects ‘explanations’ from Yerevan over Zelensky’s statements – Kremlin | Moscow expects explanations Yerevan Zelensky |
| 107 | 0.288 | no | off | pt | Folha de S.Paulo | R�ssia e Ucr�nia trocam acusa��es de ataques e colocam cessar-fogo em risco | Rússia Ucrânia cessar-fogo ataques risco |
| 108 | 0.288 | no | off | ru | Meduza | «Немного подтолкнули мы его». Зеленский заявил, что сейчас Путин «наконец готов к реальным | Зеленский Путин подтолкнули реальным переговорам |
| 109 | 0.288 | no | off | es | Infobae | Albares presiona a los Veintisiete para someter a voto suspensión parcial del Acuerdo de A | Albares Veintisiete suspensión Acuerdo Asociación |
| 110 | 0.285 | no | off | en | Anadolu Agency | Iraqi security official denies reports of secret Israeli base in Iraq’s desert | Iraqi security official denies secret Israeli base Iraq |
| 111 | 0.284 | no | on | en | Press TV | Modi warns Iran war poses great risks to India, urges reductions in fuel use | Modi warns Iran war poses risks India urges fuel reductions — direct Iran war |
| 112 | 0.283 | no | off | pt | Folha de S.Paulo | Trump se torna grande investidor em energia de fus�o nuclear nos EUA | Trump grande investidor energia fusão nuclear EUA |
| 113 | 0.282 | no | on | en | Axios | Trump official opens door to gas tax suspension | Trump official opens door to gas tax suspension Energy Sec Wright — direct US oil response |
| 114 | 0.282 | no | off | es | El Financiero | Rusia acusa a Ucrania de romper la tregua de tres días mediada por Estados Unidos | Rusia acusa Ucrania romper tregua tres días |
| 115 | 0.281 | no | off | en | Le Monde | Iran releases Nobel Peace Prize winner Narges Mohammadi over health concerns | Iran releases Nobel Peace Prize winner Mohammadi health |
| 116 | 0.280 | no | off | es | Infobae | Podemos critica a los que usan la alerta para crear "alarmismo desmesurado" para sus "bata | Podemos critica alarmismo desmesurado batallas |
| 117 | 0.278 | no | on | de | Tagesschau | Marktbericht: Hohe Ölpreise verunsichern Anleger | Marktbericht Ölpreise hoch Trump Iran Vorschlag Frieden — direct |
| 118 | 0.277 | no | off | es | El Financiero | EU y China negocian previo a la reunión entre Trump y Xi Jinping: Pactan reunión comercial | EU y China negocian Trump y Xi Jinping reunión comercial |
| 119 | 0.274 | no | off | en | Middle East Eye | Iran’s Araghchi holds talks with Dutch foreign minister | Iran Araghchi talks Dutch foreign minister |
| 120 | 0.271 | no | off | en | Kyiv Independent | As Victory Day ceasefire draws to a close, Russian attacks kill 3 civilians, injure 16 | Victory Day ceasefire draws to a close Russian attacks 3 civilians |
| 121 | 0.271 | no | off | en | Eurasianet | New report documents how Central Asian states abet Russian sanctions-busting | Central Asian states sanctions-busting Russia |
| 122 | 0.267 | no | off | en | Kyiv Independent | Ukraine war latest: Putin says he believes war in Ukraine almost over | Ukraine war Putin almost over Victory ours Red Square |
| 123 | 0.264 | no | off | es | Infobae | Juan Daniel Oviedo denuncia discriminación en la política colombiana tras la Gran Consulta | Juan Daniel Oviedo Vicepresidencia Colombia discriminación |
| 124 | 0.257 | no | off | en | AllAfrica | Sudan: T&#xfc;rk Issues High Alert On Widening Sudan Conflict Amid Increased Use of Drones | Sudan Türk widening conflict UN high alert |
| 125 | 0.256 | no | on | en | CrisisWatch (ICG) | Iran Crisis Monitor #4 | Iran Crisis Monitor #4 Middle East war progress — direct |
| 126 | 0.256 | no | off | es | Infobae | La oposición carga contra las "provocaciones" y el "victimismo" de Ayuso en México: "Es un | Oposición provocaciones victimismo Ayuso México |
| 127 | 0.255 | no | on | en | RT | The domino effect: How Iran-Israel tensions arm pirates | The domino effect Iran-Israel tensions arm pirates Hormuz blockade — direct |
| 128 | 0.253 | no | off | en | Press TV | Man convicted of spying for CIA, Mossad executed in Iran | Man convicted spying CIA Mossad executed Iran |
| 129 | 0.247 | no | on | en | Middle East Eye | Brent crude climbs above $105 after Trump rejects Iran response | Brent crude climbs above 105 after Trump rejects Iran response — direct |
| 130 | 0.244 | no | on | en | CrisisWatch (ICG) | Iran Crisis Monitor #3 | Iran Crisis Monitor #3 Middle East war progress — direct |
| 131 | 0.243 | no | on | en | Axios | Iran, China and AI collide in Trump's legacy-defining week | Iran China AI Trump legacy-defining week Washington Beijing — direct |
| 132 | 0.240 | no | off | es | El Pais | Un hombre de Trump en la Fed | Hombre Trump Fed Kevin Warsh independencia bancos |
| 133 | 0.239 | no | off | es | El Financiero | Fernández Noroña reta a EU: ‘Saquen las listas que quieran porque no vamos a doblarnos’ | Fernández Noroña reta EU listas narco doblar |
| 134 | 0.238 | no | off | es | Infobae | De Nixon a Trump: los viajes presidenciales de EE.UU. a China en más de medio siglo | De Nixon a Trump viajes presidenciales China |
| 135 | 0.229 | no | off | de | Tagesschau | Sicherheitspolitik in Asien: Japans Abkehr vom Pazifismus | Japan Sicherheitspolitik Abkehr Pazifismus |
| 136 | 0.211 | no | off | it | ANSA | Tajani, 'il negoziatore lo sceglie l'Europa, non la Russia' | Tajani negoziatore lo sceglie Europa non Russia |
| 137 | 0.202 | no | off | en | Eurasianet | Memoir: Remembering birth of C5+1 and Uzbekistan’s awakening | C5+1 Uzbekistan awakening memoir 2016 |
| 138 | 0.194 | no | off | en | Eurasianet | Press freedom across Central Asia and Caucasus eroding at alarming rate – watchdog | Press freedom Central Asia Caucasus eroding alarming |
| 139 | 0.181 | no | off | pt | Folha de S.Paulo | A��o da PM na USP tensiona greve e vira alvo de cr�ticas da comunidade acad�mica | PM USP greve desocupação reitoria |
| 140 | 0.175 | no | off | en | Al Jazeera | Things are not going so well for Russia | Things not going well for Russia stalled advance economic |
| 141 | 0.175 | no | off | pt | Folha de S.Paulo | USP diz n�o ter sido avisada pela pol�cia sobre desocupa��o da reitoria e repudia viol�nci | USP não avisada desocupação reitoria |
| 142 | 0.165 | no | off | es | El Pais | La guerra en Irán y los vaivenes de Trump hacen de oro a la banca estadounidense en el arr | La guerra en Irán vaivenes Trump banca estadounidense beneficios trading |
| 143 | 0.149 | no | off | en | CrisisWatch (ICG) | Türkiye Charts a Distinctive Course amid Middle East Turmoil | Türkiye distinctive course Middle East shaky truce |
| 144 | 0.142 | no | off | en | South China Morning Post | Why the UAE’s Opec exit spells the beginning of the end of Gulf unity | UAE's Opec exit beginning of end Gulf unity |
