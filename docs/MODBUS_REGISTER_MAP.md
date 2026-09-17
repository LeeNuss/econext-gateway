# Grant Aerona R290 (Axen) heat pump Modbus register map

Status 2026-09-17. Everything here was read from the live bus between the Aerona Smart Controller wiring centre and the outdoor unit, cross-checked against the controller's own parameter table and, for the 6000 block, discovered with the sniffer acting as a second master. Nothing is taken from the Chofu/Aerona3 documentation: that unit uses a different layout (holding 0-102) and the Axen map does not resemble it.

## Summary of findings

- **Link:** Modbus RTU, 9600 8N2, outdoor unit is slave 251, the wiring centre is the only master. One poll cycle every 10.8 s: 168 registers in 24 exchanges, request to reply 47 ms, then 330 to 356 ms of silence before the next request.
- **Polled set:** input 0 to 103, 121, 1201 to 1238; holding 2100 to 2114, 2150, 2155, 2200 (always rejected with exception 02), 6050, 6061, 6231 to 6233, 6244, 6271, 6273.
- **The controller mirrors every polled register** as a parameter named `AXEN_REGISTER_<n>` (32-bit pairs as `<n>_<n+1>`), next to decoded parameters (`AxenOutgoingTemp`, `HPStatusComprHz`, ...). Verified over 55 samples: 8415 of 8470 readings equal the bus value, the 55 misses are register 61 which the controller stores divided by 10. Register 64 has the same float type and is probably scaled too. So the raw link is also readable through the gateway API, ten seconds late.
- **Writes:** the wiring centre writes only three registers in normal operation, all with function 06: 2101 (run request), 2107 (target outgoing temperature x10) and occasionally 2103 (bitfield). Every start is `2101=1` followed by `2107=<target>`; every stop is `2101=0`. 91 writes in the February capture, nothing else.
- **Start-up fan burst:** nothing the wiring centre writes or polls controls it; the polled fan table 6231/6232/6233/6244 tops out at 650 and the burst reaches 836 to 844. Holding **6053 = 850** is the only value in the 275-register service block at that magnitude and is the candidate for the start-up maximum. Unverified.
- **6000 block:** holding 6000 to 6274 all answer, 6275 to 6499 do not. The wiring centre reads only 10 of them. The full scan then found the same 275 offsets as input registers at 4000 and 5000, and for every one of the 275 the value at 4000+i is greater than or equal to the current holding value at 6000+i, which is greater than or equal to the value at 5000+i. So **input 4000 to 4274 is the maximum and 5000 to 5274 the minimum for each service parameter at 6000 to 6274**, and input 3000 to 3274 is a third table of the same size that reads all zero. Recognisable structures inside: a second three-step fan table at 6234 to 6236 (500/550/600) next to the known one, 6245 = 500 next to 6244 = 400, EEV max 6013 = 480, and two 21-entry curves at 6129 to 6149 and 6156 to 6176 that look like temperature-by-step tables. The whole fan group 6049 to 6054 and 6231 to 6245 has limits of 200 or 300 to 1000, an rpm range.
- **R32 sibling:** the controller carries parameters `AXEN_REGISTER_2000..2016_RW_R32`, a write block for the Aerona3 R32 variant that never appears on this bus.
- **Firmware:** input 121 = 86 is the outdoor unit firmware version the gateway reports.
- **Second master:** the sniffer's tap can transmit in the idle gap. The complete discovery run, 13.8k probes over both 16-bit register spaces, showed the heat pump answering a second master normally and the wiring centre polling undisturbed. Function codes 01 and 02 (coils, discrete inputs) are rejected as illegal function, so the unit has only the two register spaces.
- **Complete discovery result:** holding registers exist at 2100 to 2114, 2150 to 2155 and 6000 to 6274, nothing else in 0 to 65535 at stride 16 (stride 8 over 2300 to 2999 and 6275 to 8191). Input registers exist at 0 to 131, 1200 to 1238, 3000 to 3274, 4000 to 4274 and 5000 to 5274, nothing else. The wiring centre polls 0 to 103, 121 and 1201 to 1238 of those; 104 to 120 read zero, 122 to 130 read 39 to 56, 131 reads 275 (the size of the parameter tables) and 1200 reads 39. The controller's R32 write block 2000 to 2016 does not exist on this unit.
- **Bus noise:** the wiring centre's own frames get garbage lead bytes and truncated tails in bursts of 5 to 12 minutes several times a day (158 of 183k frames on 2026-09-17), with nothing of ours on the bus and the heat pump idle. The wiring centre retries with the start address shifted by one and carries on. The probe logic now pauses during such bursts instead of stopping.

## Register table

Value is the reading at 10:43 BST on 2026-09-17, heat pump idle. Signed shows 16-bit two's complement where it differs. Controller parameter is the gateway index and name that carries the same register. Confidence: confirmed = controller decode, HA mapping or bus write behaviour; inferred = from dynamics or magnitude; unknown = value only.

| Type | Addr | Value | Signed | Controller parameter | Meaning | Confidence | Source |
|---|---|---|---|---|---|---|---|
| input | 0 | 132 |  | 1147 AXEN_REGISTER_00 | constant 132, purpose unknown | unknown | bus poll |
| input | 1 | 0 |  | 1148 AXEN_REGISTER_01 |  | unknown | bus poll |
| input | 2 | 0 |  | 1149 AXEN_REGISTER_02 |  | unknown | bus poll |
| input | 3 | 0 |  | 1150 AXEN_REGISTER_03 |  | unknown | bus poll |
| input | 4 | 0 |  | 1151 AXEN_REGISTER_04 |  | unknown | bus poll |
| input | 5 | 0 |  | 1152 AXEN_REGISTER_05 |  | unknown | bus poll |
| input | 6 | 0 |  | 1153 AXEN_REGISTER_06 |  | unknown | bus poll |
| input | 7 | 1 |  | 1154 AXEN_REGISTER_07 | constant 1 | unknown | bus poll |
| input | 8 | 3 |  | 1155 AXEN_REGISTER_08 | constant 3 | unknown | bus poll |
| input | 9 | 4355 |  | 1156 AXEN_REGISTER_09 | constant 4355 = 0x1103, model or version code (also in R32 block 2008) | inferred | bus poll |
| input | 10 | 25 |  | 1157 AXEN_REGISTER_10 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 11 | 5 |  | 1158 AXEN_REGISTER_11 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 12 | 75 |  | 1159 AXEN_REGISTER_12 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 13 | 18 |  | 1160 AXEN_REGISTER_13 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 14 | 70 |  | 1161 AXEN_REGISTER_14 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 15 | 20 |  | 1162 AXEN_REGISTER_15 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 16 | 25 |  | 1163 AXEN_REGISTER_16 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 17 | 5 |  | 1164 AXEN_REGISTER_17 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 18 | 75 |  | 1165 AXEN_REGISTER_18 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 19 | 18 |  | 1166 AXEN_REGISTER_19 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 20 | 25 |  | 1167 AXEN_REGISTER_20 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 21 | 5 |  | 1168 AXEN_REGISTER_21 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 22 | 55 |  | 1169 AXEN_REGISTER_22 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 23 | 18 |  | 1170 AXEN_REGISTER_23 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 24 | 0 |  | 1171 AXEN_REGISTER_24 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 25 | 0 |  | 1172 AXEN_REGISTER_25 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 26 | 25 |  | 1173 AXEN_REGISTER_26 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 27 | 5 |  | 1174 AXEN_REGISTER_27 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 28 | 55 |  | 1175 AXEN_REGISTER_28 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 29 | 18 |  | 1176 AXEN_REGISTER_29 | setpoint echo block; 10 = 25 = HPStatusPresetTemp | unknown | bus poll |
| input | 30 | 300 |  | 1177 AXEN_REGISTER_30 | constant, see value | unknown | bus poll |
| input | 31 | 170 |  | 1178 AXEN_REGISTER_31 | constant, see value | unknown | bus poll |
| input | 32 | 0 |  | 1179 AXEN_REGISTER_32 | constant, see value | unknown | bus poll |
| input | 33 | 0 |  | 1180 AXEN_REGISTER_33 | constant, see value | unknown | bus poll |
| input | 34 | 0 |  | 1181 AXEN_REGISTER_34 | constant, see value | unknown | bus poll |
| input | 35 | 1 |  | 1182 AXEN_REGISTER_35 | constant, see value | unknown | bus poll |
| input | 36 | 0 |  | 1183 AXEN_REGISTER_36 | constant, see value | unknown | bus poll |
| input | 37 | 2 |  | 1184 AXEN_REGISTER_37 | constant, see value | unknown | bus poll |
| input | 38 | 0 |  | 1185 AXEN_REGISTER_38 | constant, see value | unknown | bus poll |
| input | 39 | 0 |  | 1186 AXEN_REGISTER_39 | constant, see value | unknown | bus poll |
| input | 40 | 0 |  | 1187 AXEN_REGISTER_40 | constant, see value | unknown | bus poll |
| input | 41 | 65036 | -500 | 1188 AXEN_REGISTER_41 | -50.0 = sensor not fitted (AxenBufferTemp) | confirmed | bus poll |
| input | 42 | 163 |  | 1189 AXEN_REGISTER_42 | return water temperature x10 (AxenReturnTemp, panel TempReturn) | confirmed | bus poll |
| input | 43 | 165 |  | 1190 AXEN_REGISTER_43 | outgoing water temperature x10 (AxenOutgoingTemp, panel TempOutlet) | confirmed | bus poll |
| input | 44 | 65036 | -500 | 1191 AXEN_REGISTER_44 | -50.0 = sensor not fitted | confirmed | bus poll |
| input | 45 | 65036 | -500 | 1192 AXEN_REGISTER_45 | -50.0 = sensor not fitted | confirmed | bus poll |
| input | 46 | 65236 | -300 | 1193 AXEN_REGISTER_46 | DHW tank temperature x10, -30.0 here = not fitted (AxenDHWTemp) | confirmed | bus poll |
| input | 47 | 65036 | -500 | 1194 AXEN_REGISTER_47 | -50.0 = sensor not fitted | confirmed | bus poll |
| input | 48 | 65236 | -300 | 1195 AXEN_REGISTER_48 | copy of 46 | inferred | bus poll |
| input | 49 | 173 |  | 1196 AXEN_REGISTER_49 | temperature x10, falls to ~4 C while running: evaporator coil | inferred | bus poll |
| input | 50 | 189 |  | 1197 AXEN_REGISTER_50 | outdoor air temperature x10 (AxenOutdoorTemp) | confirmed | bus poll |
| input | 51 | 171 |  | 1198 AXEN_REGISTER_51 | temperature x10, rises to ~23 C while running: condenser / plate HX | inferred | bus poll |
| input | 52 | 178 |  | 1199 AXEN_REGISTER_52 | discharge temperature x10 (AxenDischargeTemp) | confirmed | bus poll |
| input | 53 | 182 |  | 1200 AXEN_REGISTER_53 | suction temperature x10 (AxenSuctionTemp) | confirmed | bus poll |
| input | 54 | 0 |  | 1201 AXEN_REGISTER_54 |  | unknown | bus poll |
| input | 55 | 0 |  | 1202 AXEN_REGISTER_55 |  | unknown | bus poll |
| input | 56 | 165 |  | 1203 AXEN_REGISTER_56 | copy of 43, outgoing water temperature x10 | confirmed | bus poll |
| input | 57 | 65036 | -500 | 1204 AXEN_REGISTER_57 | -50.0 = sensor not fitted | confirmed | bus poll |
| input | 58 | 0 |  | 1205 AXEN_REGISTER_58 |  | unknown | bus poll |
| input | 59 | 0 |  | 1206 AXEN_REGISTER_59 |  | unknown | bus poll |
| input | 60 | 0 |  | 1207 AXEN_REGISTER_60 |  | unknown | bus poll |
| input | 61 | 2.0 (controller scaled) |  | 1208 AXEN_REGISTER_61 | controller stores it /10 (AXEN_REGISTER_61 = 2.0 for 20); 0-24 in Feb | inferred | bus poll |
| input | 62 | 0 |  | 1209 AXEN_REGISTER_62 | water pump speed %, 0/15/60 steps (HA pump_speed) | confirmed | bus poll |
| input | 63 | 0 |  | 1210 AXEN_REGISTER_63 | 0-15 step while running | unknown | bus poll |
| input | 64 | 0.0 (controller scaled) |  | 1211 AXEN_REGISTER_64 | controller stores it /10; 0-9 in Feb | unknown | bus poll |
| input | 65 | 0 |  | 1212 AXEN_REGISTER_65 |  | unknown | bus poll |
| input | 66 | 140 |  | 1213 AXEN_REGISTER_66 | constant 190 | unknown | bus poll |
| input | 67 | 400 |  | 1214 AXEN_REGISTER_67 | constant 410 | unknown | bus poll |
| input | 68 | 140 |  | 1215 AXEN_REGISTER_68 | constant 190 | unknown | bus poll |
| input | 69 | 290 |  | 1216 AXEN_REGISTER_69 | constant 300 | unknown | bus poll |
| input | 70 | 480 |  | 1217 AXEN_REGISTER_70 | expansion valve position, 480 idle, 120-250 running; holding 6013 = 480 | inferred | bus poll |
| input | 71 | 10 |  | 1218 AXEN_REGISTER_71 | constant 10 | unknown | bus poll |
| input | 72 | 0 |  | 1219 AXEN_REGISTER_72 | 0 idle, 446-844 running: compressor current x100 A or input power | inferred | bus poll |
| input | 73 | 0 |  | 1220 AXEN_REGISTER_73 |  | unknown | bus poll |
| input | 74 | 234 |  | 1221 AXEN_REGISTER_74 | mains voltage V (232-236) | inferred | bus poll |
| input | 75 | 0 |  | 1222 AXEN_REGISTER_75 | compressor frequency Hz, 0-66 | inferred | bus poll |
| input | 76 | 327 |  | 1223 AXEN_REGISTER_76 | DC bus voltage V (324 idle, up to 363 running) | inferred | bus poll |
| input | 77 | 0 |  | 1224 AXEN_REGISTER_77 | 0 idle, 25-43 running | unknown | bus poll |
| input | 78 | 0 |  | 1225 AXEN_REGISTER_78 | fan 1 speed /10 rpm (55 = 550 rpm) | inferred | bus poll |
| input | 79 | 0 |  | 1226 AXEN_REGISTER_79 | fan 2 speed /10 rpm | inferred | bus poll |
| input | 80 | 0 |  | 1227 AXEN_REGISTER_80 | flag 0/1 | unknown | bus poll |
| input | 81 | 0 |  | 1228 AXEN_REGISTER_81 | flag 0/1 | unknown | bus poll |
| input | 82 | 0 |  | 1229 AXEN_REGISTER_82 | state 0/2/7 | unknown | bus poll |
| input | 83 | 0 |  | 1230 AXEN_REGISTER_83 | state 0/8 | unknown | bus poll |
| input | 84 | 0 |  | 1231 AXEN_REGISTER_84 |  | unknown | bus poll |
| input | 85 | 0 |  | 1232 AXEN_REGISTER_85 |  | unknown | bus poll |
| input | 86 | 688 |  | 1233 AXEN_REGISTER_86 | high side pressure x100 bar? 5.4 idle, 8.5-12.5 running; equal to 87 when off | inferred | bus poll |
| input | 87 | 685 |  | 1234 AXEN_REGISTER_87 | low side pressure x100 bar? 5.4 idle, 3.7-4.5 running | inferred | bus poll |
| input | 88 | 0 |  | 1235 AXEN_REGISTER_88 |  | unknown | bus poll |
| input | 89 | 0 |  | 1236 AXEN_REGISTER_89 |  | unknown | bus poll |
| input | 90 | 0 |  | 1237 AXEN_REGISTER_90 |  | unknown | bus poll |
| input | 91 | 0 |  | 1238 AXEN_REGISTER_91 |  | unknown | bus poll |
| input | 92 | 0 |  | 1239 AXEN_REGISTER_92 |  | unknown | bus poll |
| input | 93 | 0 |  | 1240 AXEN_REGISTER_93 |  | unknown | bus poll |
| input | 94 | 0 |  | 1241 AXEN_REGISTER_94 |  | unknown | bus poll |
| input | 95 | 0 |  | 1242 AXEN_REGISTER_95 |  | unknown | bus poll |
| input | 96 | 0 |  | 1243 AXEN_REGISTER_96 |  | unknown | bus poll |
| input | 97 | 0 |  | 1244 AXEN_REGISTER_97 |  | unknown | bus poll |
| input | 98 | 0 |  | 1245 AXEN_REGISTER_98 |  | unknown | bus poll |
| input | 99 | 0 |  | 1246 AXEN_REGISTER_99 |  | unknown | bus poll |
| input | 100 | 0 |  | 1247 AXEN_REGISTER_100 |  | unknown | bus poll |
| input | 101 | 0 |  | 1248 AXEN_REGISTER_101 |  | unknown | bus poll |
| input | 102 | 8192 |  | 1249 AXEN_REGISTER_102 | bitfield 8192/8194 (bit 13 always set, bit 1 while running) | inferred | bus poll |
| input | 103 | 0 |  | 1250 AXEN_REGISTER_103 | 0 idle, 2 running: work mode | inferred | bus poll |
| input | 104 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 105 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 106 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 107 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 108 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 109 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 110 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 111 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 112 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 113 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 114 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 115 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 116 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 117 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 118 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 119 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 120 | 0 |  | - | reads 0, not polled | unknown | scan 2026-09-17 |
| input | 122 | 48 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 123 | 48 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 124 | 49 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 125 | 46 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 126 | 48 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 127 | 56 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 128 | 45 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 129 | 48 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 130 | 39 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 131 | 275 |  | - | size of the parameter tables? | unknown | scan 2026-09-17 |
| input | 121 | 86 |  | 1283 AXEN_REGISTER_121 | outdoor unit firmware version, gateway reports it as HP firmware 86 | confirmed | bus poll |
| input | 1200 | 39 |  | - | not polled, value only | unknown | scan 2026-09-17 |
| input | 1201 | 0 |  | 1284 AXEN_REGISTER_1201 | 0 idle, 2 running: work mode | inferred | bus poll |
| input | 1202 | 91808 |  | 1285 AXEN_REGISTER_1202_1203 | electrical energy total, 32-bit with 1203, /100 kWh (HA energy_consumed_total) | confirmed | bus poll |
| input | 1203 | 91808 |  | 1285 AXEN_REGISTER_1202_1203 (low word) |  | unknown | bus poll |
| input | 1204 | 2435 |  | 1286 AXEN_REGISTER_1204_1205 | electrical energy cooling, 32-bit with 1205, /100 kWh | confirmed | bus poll |
| input | 1205 | 2435 |  | 1286 AXEN_REGISTER_1204_1205 (low word) |  | unknown | bus poll |
| input | 1206 | 76419 |  | 1287 AXEN_REGISTER_1206_1207 | electrical energy heating, 32-bit with 1207, /100 kWh | confirmed | bus poll |
| input | 1207 | 76419 |  | 1287 AXEN_REGISTER_1206_1207 (low word) |  | unknown | bus poll |
| input | 1208 | 0 |  | 1288 AXEN_REGISTER_1208_1209 | electrical energy DHW, 32-bit with 1209, /100 kWh | confirmed | bus poll |
| input | 1209 | 0 |  | 1288 AXEN_REGISTER_1208_1209 (low word) |  | unknown | bus poll |
| input | 1210 | 17950 |  | 1289 AXEN_REGISTER_1210_1211 | thermal energy cooling, 32-bit with 1211, /100 kWh (= panel CoolingPower_all) | confirmed | bus poll |
| input | 1211 | 17950 |  | 1289 AXEN_REGISTER_1210_1211 (low word) |  | unknown | bus poll |
| input | 1212 | 396743 |  | 1290 AXEN_REGISTER_1212_1213 | thermal energy heating, 32-bit with 1213, /100 kWh (= panel HeatingPower_all) | confirmed | bus poll |
| input | 1213 | 396743 |  | 1290 AXEN_REGISTER_1212_1213 (low word) |  | unknown | bus poll |
| input | 1214 | 0 |  | 1291 AXEN_REGISTER_1214_1215 | 32-bit with 1215, 0 | unknown | bus poll |
| input | 1215 | 0 |  | 1291 AXEN_REGISTER_1214_1215 (low word) |  | unknown | bus poll |
| input | 1216 | 4806 |  | 1292 AXEN_REGISTER_1216_1217 | 32-bit with 1217, 4806 | unknown | bus poll |
| input | 1217 | 4806 |  | 1292 AXEN_REGISTER_1216_1217 (low word) |  | unknown | bus poll |
| input | 1218 | 56732 |  | 1293 AXEN_REGISTER_1218_1219 | 32-bit with 1219, 56732 | unknown | bus poll |
| input | 1219 | 56732 |  | 1293 AXEN_REGISTER_1218_1219 (low word) |  | unknown | bus poll |
| input | 1220 | 0 |  | 1294 AXEN_REGISTER_1220_1221 | 32-bit with 1221, 0 | unknown | bus poll |
| input | 1221 | 0 |  | 1294 AXEN_REGISTER_1220_1221 (low word) |  | unknown | bus poll |
| input | 1222 | 0 |  | 1295 AXEN_REGISTER_1222 |  | unknown | bus poll |
| input | 1223 | 0 |  | 1296 AXEN_REGISTER_1223 |  | unknown | bus poll |
| input | 1224 | 234 |  | 1297 AXEN_REGISTER_1224 | copy of 74, mains voltage V | inferred | bus poll |
| input | 1225 | 0 |  | 1298 AXEN_REGISTER_1225 |  | unknown | bus poll |
| input | 1226 | 0 |  | 1299 AXEN_REGISTER_1226 |  | unknown | bus poll |
| input | 1227 | 0 |  | 1300 AXEN_REGISTER_1227 |  | unknown | bus poll |
| input | 1228 | 0 |  | 1301 AXEN_REGISTER_1228 |  | unknown | bus poll |
| input | 1229 | 0 |  | 1302 AXEN_REGISTER_1229 |  | unknown | bus poll |
| input | 1230 | 4 |  | 1303 AXEN_REGISTER_1230_1231 | 32-bit with 1231; 4 idle, 784-984 running | inferred | bus poll |
| input | 1231 | 4 |  | 1303 AXEN_REGISTER_1230_1231 (low word) |  | unknown | bus poll |
| input | 1232 | 0 |  | 1304 AXEN_REGISTER_1232_1233 |  | unknown | bus poll |
| input | 1233 | 0 |  | 1304 AXEN_REGISTER_1232_1233 (low word) |  | unknown | bus poll |
| input | 1234 | 0 |  | 1305 AXEN_REGISTER_1234_1235 | 32-bit with 1235; 0 idle, 1392-7053 running: thermal power W? | inferred | bus poll |
| input | 1235 | 0 |  | 1305 AXEN_REGISTER_1234_1235 (low word) |  | unknown | bus poll |
| input | 1236 | 0 |  | 1306 AXEN_REGISTER_1236_1237 | 32-bit with 1237 | unknown | bus poll |
| input | 1237 | 0 |  | 1306 AXEN_REGISTER_1236_1237 (low word) |  | unknown | bus poll |
| input | 1238 | 0 |  | 1307 AXEN_REGISTER_1238 | 0 idle, 194-1286 running: electrical power W? | inferred | bus poll |
| input | 3000-3274 | all 0 |  | - | third table with the same 275 offsets as holding 6000-6274, all zero (defaults not populated?) | inferred | scan 2026-09-17 |
| input | 4000-4274 | see 6000 rows |  | - | maximum for each holding 6000+i parameter (holds for all 275) | confirmed | scan 2026-09-17 |
| input | 5000-5274 | see 6000 rows |  | - | minimum for each holding 6000+i parameter (holds for all 275) | confirmed | scan 2026-09-17 |
| holding | 2100 | 2 |  | 1268 AXEN_REGISTER_2100_RW | mode, panel range 0-2, always 2 | inferred | bus poll |
| holding | 2101 | 0 |  | 1269 AXEN_REGISTER_2101_RW | run request written by the wiring centre, 0 off / 1 on (range 0-3) | confirmed | bus poll |
| holding | 2102 | 0 |  | 1270 AXEN_REGISTER_2102_RW | flag 0/1 | unknown | bus poll |
| holding | 2103 | 0 |  | 1271 AXEN_REGISTER_2103_RW | bitfield: bit 0 manual defrost, bit 14 purge (HA switches); value 32 seen in Feb | confirmed | bus poll |
| holding | 2104 | 0 |  | 1272 AXEN_REGISTER_2104_RW | flag 0/1 | unknown | bus poll |
| holding | 2105 | 450 |  | 1273 AXEN_REGISTER_2105_RW | 450 = 45.0, panel range 25-75 | unknown | bus poll |
| holding | 2106 | 200 |  | 1274 AXEN_REGISTER_2106_RW | 200 = 20.0, panel range 5-25 | unknown | bus poll |
| holding | 2107 | 560 |  | 1275 AXEN_REGISTER_2107_RW | target outgoing water temperature x10, written on every start; 25-34 heating, 50-56 DHW | confirmed | bus poll |
| holding | 2108 | 50 |  | 1276 AXEN_REGISTER_2108_RW | 50 = 5.0, panel range 5-25 (hysteresis?) | unknown | bus poll |
| holding | 2109 | 270 |  | 1277 AXEN_REGISTER_2109_RW | 270 = 27.0, panel range 35-75 | unknown | bus poll |
| holding | 2110 | 120 |  | 1278 AXEN_REGISTER_2110_RW | 120 = 12.0, panel range 5-25 | unknown | bus poll |
| holding | 2111 | 350 |  | 1279 AXEN_REGISTER_2111_RW | 350 = 35.0, panel range 35-75 | unknown | bus poll |
| holding | 2112 | 50 |  | 1280 AXEN_REGISTER_2112_RW | 50 = 5.0, panel range 5-25 | unknown | bus poll |
| holding | 2113 | 270 |  | 1281 AXEN_REGISTER_2113_RW | 270 = 27.0, panel range 35-75 | unknown | bus poll |
| holding | 2114 | 250 |  | 1282 AXEN_REGISTER_2114_RW | 250 = 25.0, panel range 10-35 | unknown | bus poll |
| holding | 2150 | 0 |  | 1369 AXEN_REGISTER_2150_RW-reboot_unit | reboot outdoor unit (panel AXEN_REGISTER_2150_RW-reboot_unit) | confirmed | bus poll |
| holding | 2155 | 100 |  | 1370 AXEN_2155-uhsPumpManualPreset | water pump manual preset % (panel AXEN_2155-uhsPumpManualPreset) | confirmed | bus poll |
| holding | 2200 | 12288 |  | 1308 AXEN_REGISTER_2200_RW | polled every cycle, always rejected with exception 02 | confirmed | bus poll |
| holding | 6000 | 2 |  | - | min 0 max 5 | unknown | scan 2026-09-17 |
| holding | 6001 | 5 |  | - | min 2 max 15 | unknown | scan 2026-09-17 |
| holding | 6002 | 0 |  | - | min -10 max 15 | unknown | scan 2026-09-17 |
| holding | 6003 | 65535 | -1 | - | min -5 max 10 | unknown | scan 2026-09-17 |
| holding | 6004 | 68 |  | - | min 10 max 120 | unknown | scan 2026-09-17 |
| holding | 6005 | 68 |  | - | min 10 max 120 | unknown | scan 2026-09-17 |
| holding | 6006 | 68 |  | - | min 10 max 120 | unknown | scan 2026-09-17 |
| holding | 6007 | 400 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6008 | 400 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6009 | 400 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6010 | 65531 | -5 | - | min -15 max 0 | unknown | scan 2026-09-17 |
| holding | 6011 | 8 |  | - | min 0 max 15 | unknown | scan 2026-09-17 |
| holding | 6012 | 40 |  | - | min 20 max 90 | unknown | scan 2026-09-17 |
| holding | 6013 | 480 |  | - | 480, equals EEV idle position in input 70: EEV max steps; min 0 max 480 | inferred | scan 2026-09-17 |
| holding | 6014 | 65 |  | - | min 30 max 120 | unknown | scan 2026-09-17 |
| holding | 6015 | 105 |  | - | min 15 max 120 | unknown | scan 2026-09-17 |
| holding | 6016 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6017 | 50 |  | - | min 30 max 120 | unknown | scan 2026-09-17 |
| holding | 6018 | 65 |  | - | min 55 max 75 | unknown | scan 2026-09-17 |
| holding | 6019 | 30 |  | - | min 20 max 120 | unknown | scan 2026-09-17 |
| holding | 6020 | 0 |  | - | min 0 max 2 | unknown | scan 2026-09-17 |
| holding | 6021 | 0 |  | - | min 0 max 120 | unknown | scan 2026-09-17 |
| holding | 6022 | 0 |  | - | min 0 max 120 | unknown | scan 2026-09-17 |
| holding | 6023 | 0 |  | - | min 0 max 120 | unknown | scan 2026-09-17 |
| holding | 6024 | 0 |  | - | min 0 max 120 | unknown | scan 2026-09-17 |
| holding | 6025 | 0 |  | - | min 0 max 120 | unknown | scan 2026-09-17 |
| holding | 6026 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6027 | 5 |  | - | min 0 max 20 | unknown | scan 2026-09-17 |
| holding | 6028 | 0 |  | - | min -20 max 0 | unknown | scan 2026-09-17 |
| holding | 6029 | 5 |  | - | min 0 max 10 | unknown | scan 2026-09-17 |
| holding | 6030 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6031 | 24 |  | - | min 10 max 30 | unknown | scan 2026-09-17 |
| holding | 6032 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6033 | 3 |  | - | min 0 max 3 | unknown | scan 2026-09-17 |
| holding | 6034 | 65511 | -25 | - | min -40 max -10 | unknown | scan 2026-09-17 |
| holding | 6035 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6036 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6037 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6038 | 75 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6039 | 10 |  | - | min 0 max 40 | unknown | scan 2026-09-17 |
| holding | 6040 | 65526 | -10 | - | min -20 max 20 | unknown | scan 2026-09-17 |
| holding | 6041 | 15 |  | - | min 10 max 25 | unknown | scan 2026-09-17 |
| holding | 6042 | 10 |  | - | min 1 max 20 | unknown | scan 2026-09-17 |
| holding | 6043 | 60 |  | - | min 30 max 60 | unknown | scan 2026-09-17 |
| holding | 6044 | 2 |  | - | min 1 max 2 | unknown | scan 2026-09-17 |
| holding | 6045 | 65531 | -5 | - | min -15 max 5 | unknown | scan 2026-09-17 |
| holding | 6046 | 15 |  | - | min 10 max 100 | unknown | scan 2026-09-17 |
| holding | 6047 | 40 |  | - | min 30 max 120 | unknown | scan 2026-09-17 |
| holding | 6048 | 0 |  | - | min -10 max 15 | unknown | scan 2026-09-17 |
| holding | 6049 | 400 |  | - | min 300 max 1000 | unknown | scan 2026-09-17 |
| holding | 6050 | 100 |  | 1439 HoldingRegister_6050 | pump speed setting %, panel HoldingRegister_6050 (forum: standby/min/max = 30/50/100 defaults); min 10 max 100 | confirmed | bus poll |
| holding | 6051 | 500 |  | - | min 200 max 1000 | unknown | scan 2026-09-17 |
| holding | 6052 | 250 |  | - | min 200 max 500 | unknown | scan 2026-09-17 |
| holding | 6053 | 850 |  | - | 850, only value in the block at the start-up fan peak of 836-844 rpm; min 300 max 1000 | inferred | scan 2026-09-17 |
| holding | 6054 | 450 |  | - | min 300 max 1000 | unknown | scan 2026-09-17 |
| holding | 6055 | 40 |  | - | min 20 max 60 | unknown | scan 2026-09-17 |
| holding | 6056 | 65531 | -5 | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6057 | 0 |  | - | min 0 max 1000 | unknown | scan 2026-09-17 |
| holding | 6058 | 0 |  | - | min 0 max 1000 | unknown | scan 2026-09-17 |
| holding | 6059 | 0 |  | - | min 0 max 1000 | unknown | scan 2026-09-17 |
| holding | 6060 | 100 |  | - | min 15 max 100 | unknown | scan 2026-09-17 |
| holding | 6061 | 65 |  | 1440 HoldingRegister_6061 | pump speed setting %, panel HoldingRegister_6061; min 30 max 100 | confirmed | bus poll |
| holding | 6062 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6063 | 3 |  | - | min 0 max 10 | unknown | scan 2026-09-17 |
| holding | 6064 | 6 |  | - | min -5 max 25 | unknown | scan 2026-09-17 |
| holding | 6065 | 0 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6066 | 150 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6067 | 150 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6068 | 60 |  | - | min 20 max 100 | unknown | scan 2026-09-17 |
| holding | 6069 | 400 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6070 | 400 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6071 | 40 |  | - | min 20 max 100 | unknown | scan 2026-09-17 |
| holding | 6072 | 400 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6073 | 0 |  | - | min 0 max 480 | unknown | scan 2026-09-17 |
| holding | 6074 | 6 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6075 | 247 |  | - | min 1 max 255 | unknown | scan 2026-09-17 |
| holding | 6076 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6077 | 0 |  | - | min 0 max 3 | unknown | scan 2026-09-17 |
| holding | 6078 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6079 | 4 |  | - | min 0 max 15 | unknown | scan 2026-09-17 |
| holding | 6080 | 6 |  | - | min 0 max 15 | unknown | scan 2026-09-17 |
| holding | 6081 | 5 |  | - | min 0 max 15 | unknown | scan 2026-09-17 |
| holding | 6082 | 6 |  | - | min 0 max 15 | unknown | scan 2026-09-17 |
| holding | 6083 | 4 |  | - | min 0 max 15 | unknown | scan 2026-09-17 |
| holding | 6084 | 60 |  | - | min 30 max 100 | unknown | scan 2026-09-17 |
| holding | 6085 | 20 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6086 | 120 |  | - | min 0 max 120 | unknown | scan 2026-09-17 |
| holding | 6087 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6088 | 3 |  | - | min 1 max 10 | unknown | scan 2026-09-17 |
| holding | 6089 | 55 |  | - | min 40 max 90 | unknown | scan 2026-09-17 |
| holding | 6090 | 25 |  | - | min 20 max 90 | unknown | scan 2026-09-17 |
| holding | 6091 | 45 |  | - | min 20 max 90 | unknown | scan 2026-09-17 |
| holding | 6092 | 0 |  | - | min 0 max 60 | unknown | scan 2026-09-17 |
| holding | 6093 | 60 |  | - | min 0 max 120 | unknown | scan 2026-09-17 |
| holding | 6094 | 40 |  | - | min 30 max 50 | unknown | scan 2026-09-17 |
| holding | 6095 | 40 |  | - | min 10 max 100 | unknown | scan 2026-09-17 |
| holding | 6096 | 65521 | -15 | - | min -30 max 0 | unknown | scan 2026-09-17 |
| holding | 6097 | 90 |  | - | min 50 max 100 | unknown | scan 2026-09-17 |
| holding | 6098 | 4 |  | - | min -10 max 40 | unknown | scan 2026-09-17 |
| holding | 6099 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6100 | 10 |  | - | min 1 max 20 | unknown | scan 2026-09-17 |
| holding | 6101 | 10 |  | - | min 10 max 100 | unknown | scan 2026-09-17 |
| holding | 6102 | 4 |  | - | min 1 max 10 | unknown | scan 2026-09-17 |
| holding | 6103 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6104 | 0 |  | - | min 0 max 3 | unknown | scan 2026-09-17 |
| holding | 6105 | 10 |  | - | min 2 max 20 | unknown | scan 2026-09-17 |
| holding | 6106 | 30 |  | - | min 0 max 90 | unknown | scan 2026-09-17 |
| holding | 6107 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6108 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6109 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6110 | 0 |  | - | min 0 max 2 | unknown | scan 2026-09-17 |
| holding | 6111 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6112 | 2 |  | - | min 0 max 24 | unknown | scan 2026-09-17 |
| holding | 6113 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6114 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6115 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6116 | 5 |  | - | min 5 max 120 | unknown | scan 2026-09-17 |
| holding | 6117 | 120 |  | - | min 5 max 180 | unknown | scan 2026-09-17 |
| holding | 6118 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6119 | 15 |  | - | min 0 max 50 | unknown | scan 2026-09-17 |
| holding | 6120 | 0 |  | - | min 0 max 2 | unknown | scan 2026-09-17 |
| holding | 6121 | 17 |  | - | min 10 max 17 | unknown | scan 2026-09-17 |
| holding | 6122 | 25 |  | - | min 20 max 29 | unknown | scan 2026-09-17 |
| holding | 6123 | 0 |  | - | min 0 max 3 | unknown | scan 2026-09-17 |
| holding | 6124 | 0 |  | - | min 0 max 7 | unknown | scan 2026-09-17 |
| holding | 6125 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6126 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6127 | 0 |  | - | min 0 max 2 | unknown | scan 2026-09-17 |
| holding | 6128 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6129 | 70 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6130 | 70 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6131 | 60 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6132 | 55 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6133 | 50 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6134 | 45 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6135 | 55 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6136 | 60 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6137 | 65 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6138 | 70 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6139 | 70 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6140 | 20 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6141 | 20 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6142 | 20 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6143 | 15 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6144 | 10 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6145 | 20 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6146 | 25 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6147 | 25 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6148 | 25 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6149 | 25 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6150 | 0 |  | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6151 | 0 |  | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6152 | 65535 | -1 | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6153 | 65533 | -3 | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6154 | 65532 | -4 | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6155 | 65531 | -5 | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6156 | 60 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6157 | 50 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6158 | 50 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6159 | 35 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6160 | 30 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6161 | 45 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6162 | 20 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6163 | 20 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6164 | 15 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6165 | 10 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6166 | 10 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6167 | 50 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6168 | 50 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6169 | 55 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6170 | 55 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6171 | 70 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6172 | 50 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6173 | 50 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6174 | 55 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6175 | 55 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6176 | 70 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6177 | 18 |  | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6178 | 12 |  | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6179 | 7 |  | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6180 | 5 |  | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6181 | 4 |  | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6182 | 5 |  | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6183 | 0 |  | - | min 0 max 2 | unknown | scan 2026-09-17 |
| holding | 6184 | 1 |  | - | min 0 max 2 | unknown | scan 2026-09-17 |
| holding | 6185 | 0 |  | - | min 0 max 2 | unknown | scan 2026-09-17 |
| holding | 6186 | 2 |  | - | min 0 max 2 | unknown | scan 2026-09-17 |
| holding | 6187 | 4 |  | - | min 1 max 9 | unknown | scan 2026-09-17 |
| holding | 6188 | 4 |  | - | min 1 max 9 | unknown | scan 2026-09-17 |
| holding | 6189 | 3 |  | - | min 1 max 9 | unknown | scan 2026-09-17 |
| holding | 6190 | 6 |  | - | min 1 max 9 | unknown | scan 2026-09-17 |
| holding | 6191 | 4 |  | - | min 1 max 9 | unknown | scan 2026-09-17 |
| holding | 6192 | 4 |  | - | min 1 max 9 | unknown | scan 2026-09-17 |
| holding | 6193 | 3 |  | - | min 1 max 9 | unknown | scan 2026-09-17 |
| holding | 6194 | 6 |  | - | min 1 max 9 | unknown | scan 2026-09-17 |
| holding | 6195 | 3 |  | - | min 0 max 36 | unknown | scan 2026-09-17 |
| holding | 6196 | 3 |  | - | min 0 max 36 | unknown | scan 2026-09-17 |
| holding | 6197 | 25 |  | - | min -5 max 46 | unknown | scan 2026-09-17 |
| holding | 6198 | 35 |  | - | min -5 max 46 | unknown | scan 2026-09-17 |
| holding | 6199 | 16 |  | - | min 5 max 25 | unknown | scan 2026-09-17 |
| holding | 6200 | 10 |  | - | min 5 max 25 | unknown | scan 2026-09-17 |
| holding | 6201 | 65531 | -5 | - | min -25 max 35 | unknown | scan 2026-09-17 |
| holding | 6202 | 7 |  | - | min -25 max 35 | unknown | scan 2026-09-17 |
| holding | 6203 | 35 |  | - | min 18 max 75 | unknown | scan 2026-09-17 |
| holding | 6204 | 28 |  | - | min 18 max 75 | unknown | scan 2026-09-17 |
| holding | 6205 | 5 |  | - | min 0 max 120 | unknown | scan 2026-09-17 |
| holding | 6206 | 2 |  | - | min 0 max 120 | unknown | scan 2026-09-17 |
| holding | 6207 | 5 |  | - | min 2 max 10 | unknown | scan 2026-09-17 |
| holding | 6208 | 0 |  | - | min -10 max 0 | unknown | scan 2026-09-17 |
| holding | 6209 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6210 | 0 |  | - | min 0 max 3 | unknown | scan 2026-09-17 |
| holding | 6211 | 13 |  | - | min 5 max 50 | unknown | scan 2026-09-17 |
| holding | 6212 | 10 |  | - | min 5 max 30 | unknown | scan 2026-09-17 |
| holding | 6213 | 30 |  | - | min 5 max 100 | unknown | scan 2026-09-17 |
| holding | 6214 | 60 |  | - | min 5 max 100 | unknown | scan 2026-09-17 |
| holding | 6215 | 30 |  | - | min 5 max 100 | unknown | scan 2026-09-17 |
| holding | 6216 | 95 |  | - | min 50 max 100 | unknown | scan 2026-09-17 |
| holding | 6217 | 20 |  | - | min 5 max 50 | unknown | scan 2026-09-17 |
| holding | 6218 | 0 |  | - | min -50 max 50 | unknown | scan 2026-09-17 |
| holding | 6219 | 0 |  | - | min -50 max 50 | unknown | scan 2026-09-17 |
| holding | 6220 | 0 |  | - | min -50 max 50 | unknown | scan 2026-09-17 |
| holding | 6221 | 15 |  | - | min 10 max 100 | unknown | scan 2026-09-17 |
| holding | 6222 | 17 |  | - | min 10 max 100 | unknown | scan 2026-09-17 |
| holding | 6223 | 19 |  | - | min 10 max 100 | unknown | scan 2026-09-17 |
| holding | 6224 | 20 |  | - | min 10 max 100 | unknown | scan 2026-09-17 |
| holding | 6225 | 22 |  | - | min 10 max 100 | unknown | scan 2026-09-17 |
| holding | 6226 | 3 |  | - | min 1 max 60 | unknown | scan 2026-09-17 |
| holding | 6227 | 5 |  | - | min 1 max 60 | unknown | scan 2026-09-17 |
| holding | 6228 | 10 |  | - | min 1 max 60 | unknown | scan 2026-09-17 |
| holding | 6229 | 5 |  | - | min 1 max 60 | unknown | scan 2026-09-17 |
| holding | 6230 | 10 |  | - | min 10 max 600 | unknown | scan 2026-09-17 |
| holding | 6231 | 450 |  | 1444 H_FAN_SPEED_1_6231 | H_FAN_SPEED_1, rpm (panel); min 200 max 1000 | confirmed | bus poll |
| holding | 6232 | 570 |  | 1445 H_FAN_SPEED_2_6232 | H_FAN_SPEED_2, rpm (panel); min 200 max 1000 | confirmed | bus poll |
| holding | 6233 | 650 |  | 1446 H_FAN_SPEED_3_6233 | H_FAN_SPEED_3, rpm (panel); min 200 max 1000 | confirmed | bus poll |
| holding | 6234 | 500 |  | - | 500, second fan table step 1 (cooling?); min 200 max 1000 | inferred | scan 2026-09-17 |
| holding | 6235 | 550 |  | - | 550, second fan table step 2; min 200 max 1000 | inferred | scan 2026-09-17 |
| holding | 6236 | 600 |  | - | 600, second fan table step 3; min 200 max 1000 | inferred | scan 2026-09-17 |
| holding | 6237 | 1 |  | - | min 1 max 2 | unknown | scan 2026-09-17 |
| holding | 6238 | 2 |  | - | min 0 max 6 | unknown | scan 2026-09-17 |
| holding | 6239 | 40 |  | - | min 30 max 80 | unknown | scan 2026-09-17 |
| holding | 6240 | 25 |  | - | min 10 max 50 | unknown | scan 2026-09-17 |
| holding | 6241 | 10 |  | - | min 5 max 20 | unknown | scan 2026-09-17 |
| holding | 6242 | 50 |  | - | min 0 max 100 | unknown | scan 2026-09-17 |
| holding | 6243 | 7 |  | - | min -10 max 20 | unknown | scan 2026-09-17 |
| holding | 6244 | 400 |  | 1443 H_FAN_SPEED_0_6244 | H_FAN_SPEED_0, rpm (panel); min 200 max 1000 | confirmed | bus poll |
| holding | 6245 | 500 |  | - | 500, counterpart of 6244?; min 200 max 1000 | inferred | scan 2026-09-17 |
| holding | 6246 | 2 |  | - | min 0 max 2 | unknown | scan 2026-09-17 |
| holding | 6247 | 1 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6248 | 95 |  | - | min 80 max 120 | unknown | scan 2026-09-17 |
| holding | 6249 | 110 |  | - | min 100 max 150 | unknown | scan 2026-09-17 |
| holding | 6250 | 105 |  | - | min 100 max 150 | unknown | scan 2026-09-17 |
| holding | 6251 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6252 | 60 |  | - | min 25 max 75 | unknown | scan 2026-09-17 |
| holding | 6253 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6254 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6255 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6256 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6257 | 30 |  | - | min 5 max 60 | unknown | scan 2026-09-17 |
| holding | 6258 | 0 |  | - | min 0 max 10 | unknown | scan 2026-09-17 |
| holding | 6259 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6260 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |
| holding | 6261 | 30 |  | - | min 0 max 240 | unknown | scan 2026-09-17 |
| holding | 6262 | 30 |  | - | min 0 max 240 | unknown | scan 2026-09-17 |
| holding | 6263 | 30 |  | - | min 0 max 240 | unknown | scan 2026-09-17 |
| holding | 6264 | 30 |  | - | min 0 max 240 | unknown | scan 2026-09-17 |
| holding | 6265 | 5 |  | - | min 1 max 30 | unknown | scan 2026-09-17 |
| holding | 6266 | 60 |  | - | min 0 max 60 | unknown | scan 2026-09-17 |
| holding | 6267 | 12 |  | - | min 1 max 15 | unknown | scan 2026-09-17 |
| holding | 6268 | 7 |  | - | min 1 max 15 | unknown | scan 2026-09-17 |
| holding | 6269 | 330 |  | - | min 300 max 700 | unknown | scan 2026-09-17 |
| holding | 6270 | 30 |  | - | min 20 max 60 | unknown | scan 2026-09-17 |
| holding | 6271 | 100 |  | 1441 HoldingRegister_6271 | pump speed setting %, panel HoldingRegister_6271; min 50 max 100 | confirmed | bus poll |
| holding | 6272 | 0 |  | - | min 0 max 4 | unknown | scan 2026-09-17 |
| holding | 6273 | 0 |  | 1442 HoldingRegister_6273 | pump speed setting %, panel HoldingRegister_6273; min 0 max 100 | confirmed | bus poll |
| holding | 6274 | 0 |  | - | min 0 max 1 | unknown | scan 2026-09-17 |

## Open issues

1. **Bus noise bursts** (see summary) are not caused by probing; source unknown, heat pump and pumps idle during them. Worth a look at what else switches in the house on that rhythm, and at whether the RS-485 pair has failsafe biasing.
2. **Discovery is complete** for both register spaces at stride 16 (stride 8 in the two likely areas). Blocks shorter than 8 registers outside the fine-scanned ranges are the only thing that could still hide.
3. **Unverified meanings** are marked inferred or unknown above. The 10 to 29 block, the 30 to 40 constants and most of the 6000 block need either the controller's decode (none exists for them) or a controlled change on the panel while watching the bus.
4. **Register 64 scaling** by the controller is assumed from its float type; it has read 0 throughout.

## Data

- `docs/scans/2026-09-17_holding_6000-6499.tsv`: the 6000 block scan.
- `docs/scans/2026-09-17_holding_full.tsv`, `..._input_full.tsv`: the complete discovery run (fine ranges plus stride-16 sweeps), `..._holding_stride8.tsv`, `..._input_stride8.tsv`: stride-8 passes over 2300 to 2999 and 6275/6500 to 8191, `..._coil.tsv`, `..._discrete.tsv`: function codes 01 and 02 rejected.
- February and March 2026 capture (5 h heating, 91 writes): `emonhp:/home/pi/modbus_capture_feb_mar.db`, old SQLite schema, replay with `modbus-sniffer changes --db`.
- Continuous capture since 2026-09-16: hourly chunks on the Pi, daily files on the NAS under `/mnt/nas/modbus/YYYY/MM/`.
- Controller parameter samples every 10 s since 2026-09-17 09:05: `emonhp:/var/tmp/params.jsonl`, matcher `tools/axen_param_match.py`.
