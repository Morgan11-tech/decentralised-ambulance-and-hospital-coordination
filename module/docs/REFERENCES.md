# References

Every source used for a parameter value, target or experiment range. Each entry was
checked (DOI resolved via Crossref, or the page/PDF read) on 2026-10-18; the call-processing sources
and the Contract Net details were checked on 2026-10-19, and the control-room staffing source on 2026-10-19; the 2019 outage memo and the 2024 parliamentary answers on 2026-10-28. The "Used for"
line says exactly which number or design choice relies on it.

## Dutch data (calibration and parameters)

**RIVM / VZinfo.** *Acute zorg — Ambulancezorg, regionaal.* (Figures from Sectorkompas Ambulancezorg 2025.)
https://www.vzinfo.nl/acute-zorg/regionaal/ambulancezorg
- Used for: the 15-min A1 norm (12 min drive + 3 min "meld- en uitruktijd", i.e. call handling and turnout);
 target p95 band (national 16:57 in
  2025, regions 15:08–18:20); 98.1% population coverage (24/7, geographic); national urgency counts 2025
  (A0 28,159 · A1 724,732 · A2 452,611 · B 308,686) → severity mix.
- Note: the brief quoted 16:51 and 14:38–18:36. Those are earlier-year figures; the page now shows the 2025 values above.

**Ambulancezorg Nederland (2019).** *Urgenties ambulancezorg: bevindingen* (factsheet, September 2019).
https://ambulancezorg.nl/static/upload/raw/dbb6d471-f8de-45b1-a26c-8f477a242e9d/Factsheet+Urgenties+ambulancezorg+bevindingen+2019.TLP-Wit.pdf
- Used for: the **30-min A2 norm** ("De bijbehorende streefnormen voor de responstijd zijn 15 en 30 minuten"),
  used for the A2 metric and the A2 reference line. The same factsheet notes that neither norm is
  scientifically grounded.

**Tweede Kamer der Staten-Generaal (2025).** *Aanhangsel van de Handelingen 2025–2026, nr. 747: answers of
the Minister of VWS to questions on the number of urgent dispatches of Ambulance Oost* (19 Dec 2025), Table 1.
https://berthub.eu/tkconv/getraw/2025D53564
- Used for: normal demand — 23,238 A1 (incl. A0) dispatches in Twente in 2024 → 2.65 urgent calls/hour.

**Ambulance Oost (RAV Twente).** https://ambulanceoost.nl
- Used for: region (14 municipalities, ~639k residents), fleet (~32 vehicles), 11 posts, ~45,000 patients/yr.
- Note: the site itself gives conflicting numbers (32 vs 33 ambulances, 9 vs 11 posts, 41k vs 45k patients).

**Mol, Hageman-van Wamel, Van der Linden, Gaakeer, De Ridder (2025).** *Waiting time ambulances in the Emergency
Department; a Dutch single center study (WAITED study).* International Journal of Emergency Medicine, 18.
https://doi.org/10.1186/s12245-025-01068-y
- Used for: offload target — 229 of 2,967 arrivals (7.7%) met the offload-delay criterion, median 16 min;
  handover 12 min (~96% of handovers < 15 min). Single hospital group (Rotterdam), not Twente.

**Baan-Kooman, Mol, van der Linden, Gaakeer (2025).** *Emergency department crowding in the Netherlands;
evaluation of a real-time ambulance diversion dashboard.* International Journal of Emergency Medicine.
https://doi.org/10.1186/s12245-024-00784-1
- Used for: diversion mechanics (1–2 h window, reopening once crowding subsides).

**de Graaf, Donders, Beesems, Henriques, Koster (2020).** *Time to Return of Spontaneous Circulation and Survival:
When to Transport in out-of-Hospital Cardiac Arrest?* Prehospital Emergency Care.
https://doi.org/10.1080/10903127.2020.1752868
**de Graaf, de Kruif, Beesems, Koster et al. (2021).** *To transport or to terminate resuscitation on-site. What
factors influence EMS decisions in patients without ROSC?* Resuscitation 164, 84–92.
https://doi.org/10.1016/j.resuscitation.2021.05.005
- Used for: A0 (cardiac arrest) on-scene time and transport probability (Amsterdam ARREST registry).

**Citerio, G., Galli, D., Pesenti, A., et al. (2006).** *Early stroke care in Italy — a steep way ahead:
an observational study.* Emergency Medicine Journal, 23(8), 608–611. https://doi.org/10.1136/emj.2005.032219
(PMID 16858091; https://emj.bmj.com/content/23/8/608)
- Used for: call-processing latency — mean **2.3 ± 2 min** between call and ambulance dispatch (13 EMS dispatch
  centres in five Italian regions, 1,041 suspected-stroke calls) → `DISPATCH_HANDLING_MIN = 2`.
- Note: Italian, 2006, stroke calls only; older than the 2020+ preference, used because no Dutch per-call figure
  was found. Checked via the PubMed/Europe PMC abstract (the journal page refused automated access).

**Netwerk Acute Zorg regio Zwolle (n.d., ≥ 2 years old).** *Werkbezoek meldkamer Oost-Nederland: een kijkje
achter de schermen.*
https://netwerkacutezorg.nl/werkbezoek-meldkamer-oost-nederland-een-kijkje-achter-de-schermen/
- Used for: `N_DISPATCH_OPERATORS = 1`. Meldkamer Oost-Nederland (Apeldoorn) serves five regions incl. Twente
  (3.2 M residents, 12,000 ambulance 112 calls/month). Its 112 team has "overdag 4, 's avonds 4 en 's nachts 3
  centralisten … naar rato aangeleverd door elk van de 5 regio's". Twente's population share (639k / 3.2 M)
  gives 0.6–0.8 call-takers → 1 (`[ASSUMPTION]`: pro-rata; the real team is pooled across regions).
- Also used for: keeping call-taking running during a dispatcher outage. Another control room can take the 112
  call, but "de uitgifte wordt dan nog altijd in de eigen regio gedaan".
- Note: an undated news page, not a staffing report. The RIVM *Capaciteitsmodel meldkamer ambulancezorg 2022*
  (report 2022-0167) gives only a national total (122 centralists, weekday daytime), so it could not be used
  per region. https://www.rivm.nl/publicaties/capaciteitsmodel-meldkamer-ambulancezorg-2022

**Veiligheidsregio Twente (2019).** *Landelijke storing 112, effecten Twente* (memo for the board meeting of
14 October 2019, document F02a). [VRT-2019]
https://www.vrtwente.nl/sites/vrt/files/vergaderstukken/20191014%20F02a%20Landelijke%20storing%20112%20twente%20concept%20beschrijving.pdf
- Used for (results summary, stakeholder section only; no model parameter): the 24 June 2019 national 112 outage
  as handled in Twente. Timeline: start around 16:00, GRIP 2 at 16:49, regional numbers shared at 17:15,
  NL-Alert for Twente at 18:14, 112 reachable again at 19:27. Measures: regional emergency numbers (incl.
  053-4557820 for the ambulance), all 29 fire stations staffed, ambulances posted at police stations, radio link
  between hospitals and moving ambulances.
- Note: this was a failure of calls getting *in* (112 unreachable), not of dispatch. The times are not a
  measured switchover delay.

**Tweede Kamer der Staten-Generaal (2024).** *Aanhangsel van de Handelingen 2023–2024, nr. 2037: answers of the
Minister for Medical Care to questions by member Claassen on "Crisis in Meldkamer Oost Nederland"* (received
21 June 2024). [TK-2024-2037] https://zoek.officielebekendmakingen.nl/ah-tk-20232024-2037.pdf
- Used for (results summary, stakeholder section only): IGJ "houdt momenteel geïntensiveerd toezicht op de
  meldkamer ambulancezorg Oost-Nederland" because of staffing; 112 systems re-route calls to regions with capacity
  when busy; pilots to run the ambulance control-room function partly outside the meldkamer; Push-to-Talk app
  used alongside C2000, with C2000 handhelds and regular telephony as backup; non-urgent desks in Hengelo,
  Zwolle and Arnhem.
- Note: describes the situation in June 2024; the current status of the supervision was not checked.

**NASEMSO (2024).** *EMS Time Interval Definitions* (NEMSIS v3.5 data dictionary). National Association of State
EMS Officials, updated 14 May 2024.
https://nemsis.org/wp-content/uploads/2024/06/NASEMSO_EMS_Time_Duration_Definitions-6-18-24.pdf
- Used for: the definition of the simulated latency — "PSAP to Unit Notified Time" (unit notified − PSAP call),
  kept separate from "Unit Notified to En Route Time (Chute Time)", which the model does not simulate.

## Modelling and methods

**Smith, R. G. (1980).** *The Contract Net Protocol: High-Level Communication and Control in a Distributed
Problem Solver.* IEEE Transactions on Computers, C-29(12), 1104–1113. https://doi.org/10.1109/TC.1980.1675516
- Used for: the decentralized condition (announce → bid → award). Checked in the paper itself: each task
  announcement carries a contract number and an "expiration time", which "is a deadline for receiving bids";
  late bids "at worst … may result in a suboptimum selection". This is the basis for the fixed bidding window,
  for tagging bids with the announcement they answer, and for the E5 window study.

**Ballou, R. H., Rahardja, H., Sakai, N. (2002).** *Selected country circuity factors for road travel distance
estimation.* Transportation Research Part A, 36(9), 843–848. https://doi.org/10.1016/S0965-8564(01)00044-1
- Used for: the idea of a detour (circuity) multiplier on straight-line distance. We did not verify a
  Netherlands-specific value from the paper; `DETOUR_FACTOR = 1.3` remains `[ASSUMPTION]`.

**Kolker, A. (2008).** *Process Modeling of Emergency Department Patient Flow: Effect of Patient Length of Stay on
ED Diversion.* Journal of Medical Systems. https://link.springer.com/article/10.1007/s10916-008-9144-x
- Used for: the server/length-of-stay ED model and its link to diversion.

**De Santis, Iannazzo, Ingravalle, Lucidi, Maurici, Riccardi, Roma, Vinci (2026).** *A Realistic Discrete Event
Simulation model for Ambulance Location and Deployment within a regional Emergency Medical Service.*
arXiv:2604.24394 (preprint). https://arxiv.org/abs/2604.24394
- Used for: as a reference point for regional EMS DES design (scenario analysis on a real region). We did not
  take specific replication/warm-up numbers from it.

## Related work (positioning, experiment ranges)

**Ibri, S., Nourelfath, M., Drias, H. (2012).** *A multi-agent approach for integrated emergency vehicle dispatching
and covering problem.* Engineering Applications of Artificial Intelligence, 25(3), 554–565.
https://doi.org/10.1016/j.engappai.2011.10.003
- Used for: prior multi-agent EMS dispatch; assumes reliable communication.

**Umam, M. I. H., Kurnianingtyas, D., Santosa, B., Siswanto, N. (2019).** *Decentralization of Medical Emergency
Service to Minimize Response Time.* Proc. IEOM 2019, Bangkok. https://www.ieomsociety.org/ieom2019/papers/278.pdf
- Used for: precedent for varying demand levels and time limits; reports decentralized faster (avg 3–6 min vs
  10–13 min). Note: their "decentralized" means allocation/redeployment optimised per area, not agent bidding.

**Deo, S., Gurvich, I. (2011).** *Centralized vs. Decentralized Ambulance Diversion: A Network Perspective.*
Management Science, 57(7), 1300–1319. https://doi.org/10.1287/mnsc.1110.1342
- Used for: evidence that uncoordinated (decentralized) diversion can produce a "defensive" equilibrium with
  higher delays. Shows the literature is split.

**Lee, S. (2012).** *The role of centrality in ambulance dispatching.* Decision Support Systems, 54(1), 282–291.
https://doi.org/10.1016/j.dss.2012.05.036
- Used for: precedent for reporting both mean and variance of response time, and for disaster-load scenarios.

**Zarkeshzadeh, M., Zare, H., Heshmati, Z., Teimouri, M. (2016).** *A novel hybrid method for improving ambulance
dispatching response time through a simulation study.* Simulation Modelling Practice and Theory, 60, 170–184.
https://doi.org/10.1016/j.simpat.2015.10.004
- Used for: precedent for sweeping call rate and resources.

**Larsen, M. P., Eisenberg, M. S., Cummins, R. O., Hallstrom, A. P. (1993).** *Predicting survival from
out-of-hospital cardiac arrest: a graphic model.* Annals of Emergency Medicine, 22(11), 1652–1658.
https://doi.org/10.1016/S0196-0644(05)81302-2
- Used for: arguing (not simulating) why minutes matter for A0 calls. Not used to compute any model output.

## Not cited

The brief mentioned a "metaheuristic ambulance-allocation study (2023)" as justification for ≥ 8 seeds and a
"Cheng 2014" surge study. Neither came with enough detail to identify and verify, so neither is cited. The
seed count is instead justified by our own confidence intervals (see DECISIONS.md, §7).
