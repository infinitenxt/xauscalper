//+------------------------------------------------------------------+
//|                                          BTC_Universal_Bridge    |
//|                           Universal BTC/USD Bridge for any broker|
//|                                                                   |
//+------------------------------------------------------------------+
#property copyright "Bitcoin Universal Bridge"
#property version   "3.0"
#property strict
#property description "Universal BTC bridge — auto-detects any BTC symbol"
#property description "Supports: BTCUSD, BTCUSDT, XBTUSD, BTCUSD.p, etc."
#property description "FIXED: No WebRequest blocking, auto-symbol detection"

#include <Trade/Trade.mqh>

// ---------- Inputs ----------
input string BridgeUrl = "https://trade.infinitenxt.com/api/mt5/bridge";
input string BridgeToken = "PASTE_YOUR_TOKEN";
input string ManualSymbol = "";              // auto-detect
input int PollSeconds = 3;
input ulong MagicNumber = 860081;
input int MaxDeviationPoints = 80;
input string EaVersion = "3.0";

// ---------- Globals ----------
CTrade trade;
string gv_prefix = "GPT_MT5_";
string journal_file = "";
string detected_symbol = "";
bool webrequest_ready = false;
datetime last_heartbeat = 0;
datetime last_poll = 0;
int init_attempts = 0;

// ---------- BTC Symbol Patterns (Universal) ----------
string BTC_PATTERNS[] = {
   "BTCUSD", "BTCUSDT", "XBTUSD", "BTCUSD.p", "BTCUSDT.p",
   "BTC/USD", "BTC/USDT", "XBT/USD", "BTC.CMD", "BTC",
   "BITCOIN", "BTCSPOT", "BTCUSD.c", "BTCUSD.n", "BTCUSDm",
   "BTCUSDTm", "XBTUSDT"
};

//+------------------------------------------------------------------+
//| Escape JSON string                                               |
//+------------------------------------------------------------------+
string EscapeJson(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\r", "\\r");
   return value;
}

//+------------------------------------------------------------------+
//| Check if symbol is BTC-related (Universal)                       |
//+------------------------------------------------------------------+
bool IsBTCSymbol(string symbol)
{
   if(symbol == "") return false;
   
   string upper = symbol;
   StringToUpper(upper);
   StringReplace(upper, "/", "");
   StringReplace(upper, ".", "");
   StringReplace(upper, "_", "");
   StringReplace(upper, "-", "");
   StringReplace(upper, ":", "");
   
   // Exact match
   for(int i = 0; i < ArraySize(BTC_PATTERNS); i++) {
      string pattern = BTC_PATTERNS[i];
      StringToUpper(pattern);
      StringReplace(pattern, "/", "");
      StringReplace(pattern, ".", "");
      StringReplace(pattern, "_", "");
      StringReplace(pattern, "-", "");
      StringReplace(pattern, ":", "");
      
      if(upper == pattern) return true;
   }
   
   // Pattern match: contains BTC and USD
   if(StringFind(upper, "BTC") >= 0 && (StringFind(upper, "USD") >= 0 || StringFind(upper, "USDT") >= 0)) {
      // Exclude non-BTC symbols like GBTC, EBTC, etc.
      if(StringFind(upper, "GBTC") < 0 && StringFind(upper, "EBTC") < 0 && StringFind(upper, "SBTC") < 0) {
         return true;
      }
   }
   
   return false;
}

//+------------------------------------------------------------------+
//| Auto-detect BTC symbol (Universal)                               |
//+------------------------------------------------------------------+
string DetectBTCSymbol()
{
   Print("🔍 Searching for BTC symbol...");
   
   // 1. Manual override
   if(ManualSymbol != "" && SymbolSelect(ManualSymbol, true) && IsBTCSymbol(ManualSymbol)) {
      Print("✅ Using manual symbol: ", ManualSymbol);
      return ManualSymbol;
   }
   
   // 2. Check Market Watch first (faster)
   int total = SymbolsTotal(false);
   for(int i = 0; i < total; i++) {
      string name = SymbolName(i, false);
      if(IsBTCSymbol(name)) {
         SymbolSelect(name, true);
         Print("✅ Detected BTC symbol in Market Watch: ", name);
         return name;
      }
   }
   
   // 3. Check all symbols (including custom)
   total = SymbolsTotal(true);
   for(int i = 0; i < total; i++) {
      string name = SymbolName(i, true);
      if(IsBTCSymbol(name)) {
         SymbolSelect(name, true);
         Print("✅ Detected BTC symbol in All Symbols: ", name);
         return name;
      }
   }
   
   // 4. Try common symbols directly
   string common[] = {"BTCUSD", "BTCUSDT", "XBTUSD", "BTCUSD.p", "BTCUSDT.p"};
   for(int i = 0; i < ArraySize(common); i++) {
      if(SymbolSelect(common[i], true)) {
         Print("✅ Found BTC symbol by direct check: ", common[i]);
         return common[i];
      }
   }
   
   Print("❌ No BTC symbol found! Please add BTCUSD or BTCUSDT to Market Watch.");
   return "";
}

//+------------------------------------------------------------------+
//| HTTP POST request                                                |
//+------------------------------------------------------------------+
bool ApiPost(string endpoint, string body, string &response)
{
   if(!webrequest_ready) {
      Print("⚠️ WebRequest not ready. Please whitelist URL in MT5:");
      Print("   Tools → Options → Expert Advisors → Allow WebRequest");
      Print("   Add: ", BridgeUrl);
      response = "";
      return false;
   }
   
   char data[];
   char result[];
   string response_headers;
   
   StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(data) > 0) ArrayResize(data, ArraySize(data) - 1);
   
   string headers = "Content-Type: application/json\r\nAuthorization: Bearer " + BridgeToken + "\r\n";
   
   ResetLastError();
   int status = WebRequest("POST", BridgeUrl + endpoint, headers, 8000, data, result, response_headers);
   response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   
   if(status < 200 || status >= 300) {
      Print("❌ Bridge request failed: endpoint=", endpoint, " HTTP=", status, " error=", GetLastError());
      if(status == 0) {
         Print("   ⚠️ HTTP 0 means WebRequest is blocked. Whitelist the URL!");
      }
      return false;
   }
   
   return true;
}

//+------------------------------------------------------------------+
//| JSON helpers                                                     |
//+------------------------------------------------------------------+
string JsonString(string json, string key)
{
   string marker = "\"" + key + "\"";
   int p = StringFind(json, marker);
   if(p < 0) return "";
   p = StringFind(json, ":", p + StringLen(marker));
   if(p < 0) return "";
   p++;
   while(p < StringLen(json) && StringGetCharacter(json, p) <= 32) p++;
   if(StringSubstr(json, p, 4) == "null") return "";
   if(StringGetCharacter(json, p) != 34) return "";
   p++;
   int end = p;
   while(end < StringLen(json)) {
      if(StringGetCharacter(json, end) == 34 && (end == p || StringGetCharacter(json, end - 1) != 92)) break;
      end++;
   }
   return StringSubstr(json, p, end - p);
}

double JsonNumber(string json, string key, double fallback = 0.0)
{
   string marker = "\"" + key + "\"";
   int p = StringFind(json, marker);
   if(p < 0) return fallback;
   p = StringFind(json, ":", p + StringLen(marker));
   if(p < 0) return fallback;
   p++;
   while(p < StringLen(json) && StringGetCharacter(json, p) <= 32) p++;
   int end = p;
   while(end < StringLen(json)) {
      ushort c = (ushort)StringGetCharacter(json, end);
      if(!((c >= 48 && c <= 57) || c == 45 || c == 43 || c == 46 || c == 101 || c == 69)) break;
      end++;
   }
   string raw = StringSubstr(json, p, end - p);
   return raw == "" ? fallback : StringToDouble(raw);
}

//+------------------------------------------------------------------+
//| Position functions                                               |
//+------------------------------------------------------------------+
bool PositionByMagic(ulong &ticket)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong current = PositionGetTicket(i);
      if(current == 0 || !PositionSelectByTicket(current)) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) == MagicNumber && PositionGetString(POSITION_SYMBOL) == detected_symbol) {
         ticket = current;
         return true;
      }
   }
   ticket = 0;
   return false;
}

bool TradeRequestAccepted()
{
   uint code = trade.ResultRetcode();
   return code == TRADE_RETCODE_DONE || code == TRADE_RETCODE_DONE_PARTIAL || code == TRADE_RETCODE_PLACED;
}

bool CommandWasExecuted(string command_id)
{
   int handle = FileOpen(journal_file, FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(handle == INVALID_HANDLE) return false;
   bool found = false;
   while(!FileIsEnding(handle)) {
      if(FileReadString(handle) == command_id) { found = true; break; }
   }
   FileClose(handle);
   return found;
}

void RememberExecutedCommand(string command_id)
{
   if(command_id == "" || CommandWasExecuted(command_id)) return;
   int handle = FileOpen(journal_file, FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(handle == INVALID_HANDLE)
      handle = FileOpen(journal_file, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(handle == INVALID_HANDLE) {
      Print("Could not persist MT5 command journal: ", GetLastError());
      return;
   }
   FileSeek(handle, 0, SEEK_END);
   FileWrite(handle, command_id);
   FileFlush(handle);
   FileClose(handle);
}

double DailyProfit()
{
   MqlDateTime parts;
   TimeToStruct(TimeCurrent(), parts);
   parts.hour = 0; parts.min = 0; parts.sec = 0;
   datetime start = StructToTime(parts);
   if(!HistorySelect(start, TimeCurrent())) return 0.0;
   double result = 0.0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++) {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
      ENUM_DEAL_TYPE type = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);
      if(type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL) continue;
      result += HistoryDealGetDouble(ticket, DEAL_PROFIT);
      result += HistoryDealGetDouble(ticket, DEAL_SWAP);
      result += HistoryDealGetDouble(ticket, DEAL_COMMISSION);
   }
   return result;
}

string PositionJson()
{
   ulong ticket;
   if(!PositionByMagic(ticket) || !PositionSelectByTicket(ticket)) return "[]";
   string direction = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "BUY" : "SELL";
   return "[{\"ticket\":\"" + (string)ticket + "\",\"symbol\":\"" + EscapeJson(detected_symbol) +
      "\",\"direction\":\"" + direction + "\",\"volume\":" + DoubleToString(PositionGetDouble(POSITION_VOLUME), 4) +
      ",\"entry_price\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), (int)SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS)) +
      ",\"current_price\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_CURRENT), (int)SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS)) +
      ",\"sl\":" + DoubleToString(PositionGetDouble(POSITION_SL), (int)SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS)) +
      ",\"tp\":" + DoubleToString(PositionGetDouble(POSITION_TP), (int)SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS)) +
      ",\"profit\":" + DoubleToString(PositionGetDouble(POSITION_PROFIT), 2) +
      ",\"opened_at\":" + (string)PositionGetInteger(POSITION_TIME) + "}]";
}

//+------------------------------------------------------------------+
//| Send Heartbeat (ALL FIELDS INCLUDED)                             |
//+------------------------------------------------------------------+
void SendHeartbeat()
{
   if(detected_symbol == "") return;
   
   // All required fields
   double volume_min = SymbolInfoDouble(detected_symbol, SYMBOL_VOLUME_MIN);
   double volume_max = SymbolInfoDouble(detected_symbol, SYMBOL_VOLUME_MAX);
   double volume_step = SymbolInfoDouble(detected_symbol, SYMBOL_VOLUME_STEP);
   int digits = (int)SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS);
   double spread = (SymbolInfoDouble(detected_symbol, SYMBOL_ASK) - SymbolInfoDouble(detected_symbol, SYMBOL_BID)) / SymbolInfoDouble(detected_symbol, SYMBOL_POINT);
   
   bool demo = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO;
   
   string body = "{"
      "\"account_login\":\"" + (string)AccountInfoInteger(ACCOUNT_LOGIN) + "\","
      "\"broker_server\":\"" + EscapeJson(AccountInfoString(ACCOUNT_SERVER)) + "\","
      "\"is_demo\":" + (demo ? "true" : "false") + ","
      "\"resolved_symbol\":\"" + EscapeJson(detected_symbol) + "\","
      "\"balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ","
      "\"equity\":" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + ","
      "\"margin\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN), 2) + ","
      "\"free_margin\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) + ","
      "\"margin_level\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_LEVEL), 2) + ","
      "\"account_currency\":\"" + EscapeJson(AccountInfoString(ACCOUNT_CURRENCY)) + "\","
      "\"daily_profit\":" + DoubleToString(DailyProfit(), 2) + ","
      "\"volume_min\":" + DoubleToString(volume_min, 4) + ","
      "\"volume_max\":" + DoubleToString(volume_max, 4) + ","
      "\"volume_step\":" + DoubleToString(volume_step, 4) + ","
      "\"digits\":" + (string)digits + ","
      "\"spread\":" + DoubleToString(spread, 0) + ","
      "\"trade_allowed\":" + (AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) ? "true" : "false") + ","
      "\"algo_trading\":" + (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED) ? "true" : "false") + ","
      "\"ea_version\":\"" + EscapeJson(EaVersion) + "\","
      "\"terminal_build\":" + (string)TerminalInfoInteger(TERMINAL_BUILD) + ","
      "\"positions\":" + PositionJson() +
   "}";
   
   string response;
   if(ApiPost("/heartbeat", body, response)) {
      // Print("✅ Heartbeat sent"); // Commented to reduce log spam
   } else {
      Print("❌ Heartbeat failed");
   }
}

//+------------------------------------------------------------------+
//| Execute Entry                                                    |
//+------------------------------------------------------------------+
string ExecuteEntry(string json, string &message, ulong &ticket)
{
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED) || !AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)) {
      message = "Trading or Algo Trading is disabled";
      return "rejected";
   }
   
   ulong existing;
   if(PositionByMagic(existing)) {
      ticket = existing;
      message = "Entry already executed; idempotent confirmation";
      return "executed";
   }
   
   string side = JsonString(json, "direction");
   double lots = JsonNumber(json, "lots");
   double sl_distance = JsonNumber(json, "sl_dist");
   double tp_distance = JsonNumber(json, "tp_dist");
   
   if(side != "BUY" && side != "SELL") {
      message = "Unsupported entry direction";
      return "rejected";
   }
   
   double vmin = SymbolInfoDouble(detected_symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(detected_symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(detected_symbol, SYMBOL_VOLUME_STEP);
   
   if(lots < vmin || lots > vmax) {
      message = "Lot outside broker min/max";
      return "rejected";
   }
   
   double steps = (lots - vmin) / step;
   if(MathAbs(steps - MathRound(steps)) > 0.000001) {
      message = "Lot does not match broker step";
      return "rejected";
   }
   
   ENUM_ORDER_TYPE type = side == "BUY" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double price = side == "BUY" ? SymbolInfoDouble(detected_symbol, SYMBOL_ASK) : SymbolInfoDouble(detected_symbol, SYMBOL_BID);
   
   if(price <= 0) {
      message = "Invalid live market price";
      return "rejected";
   }
   
   int stops = (int)SymbolInfoInteger(detected_symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double point = SymbolInfoDouble(detected_symbol, SYMBOL_POINT);
   double min_stop_distance = stops * point;
   
   sl_distance = MathMax(sl_distance, min_stop_distance);
   tp_distance = MathMax(tp_distance, min_stop_distance);
   
   double sl = 0.0, tp = 0.0;
   int digits = (int)SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS);
   
   if(side == "BUY") {
      sl = NormalizeDouble(price - sl_distance, digits);
      tp = NormalizeDouble(price + tp_distance, digits);
   } else {
      sl = NormalizeDouble(price + sl_distance, digits);
      tp = NormalizeDouble(price - tp_distance, digits);
   }
   
   if(sl <= 0 || tp <= 0) {
      message = "Invalid SL/TP";
      return "rejected";
   }
   
   double margin = 0.0;
   if(!OrderCalcMargin(type, detected_symbol, lots, price, margin) || margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE)) {
      message = "Insufficient free margin";
      return "rejected";
   }
   
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(MaxDeviationPoints);
   trade.SetTypeFillingBySymbol(detected_symbol);
   
   bool ok = side == "BUY" ? trade.Buy(lots, detected_symbol, price, sl, tp, "BTC Bridge") : trade.Sell(lots, detected_symbol, price, sl, tp, "BTC Bridge");
   message = trade.ResultRetcodeDescription();
   
   if(!ok || !TradeRequestAccepted()) return "failed";
   
   Sleep(200);
   if(PositionByMagic(ticket) && PositionSelectByTicket(ticket)) {
      return "executed";
   }
   
   return "accepted";
}

//+------------------------------------------------------------------+
//| Send Acknowledgement                                             |
//+------------------------------------------------------------------+
void SendAck(string command_id, string outcome, ulong ticket, string message)
{
   double price = 0.0, volume = 0.0;
   if(ticket > 0 && PositionSelectByTicket(ticket)) {
      price = PositionGetDouble(POSITION_PRICE_OPEN);
      volume = PositionGetDouble(POSITION_VOLUME);
   }
   
   bool success = outcome == "executed" || outcome == "accepted";
   string body = "{"
      "\"command_id\":\"" + EscapeJson(command_id) + "\","
      "\"success\":" + (success ? "true" : "false") + ","
      "\"result\":\"" + EscapeJson(outcome) + "\","
      "\"broker_ticket\":" + (ticket > 0 ? "\"" + (string)ticket + "\"" : "null") + ","
      "\"broker_deal\":" + (trade.ResultDeal() > 0 ? "\"" + (string)trade.ResultDeal() + "\"" : "null") + ","
      "\"broker_retcode\":" + (string)trade.ResultRetcode() + ","
      "\"broker_message\":\"" + EscapeJson(message) + "\","
      "\"filled_price\":" + DoubleToString(price, 5) + ","
      "\"filled_volume\":" + DoubleToString(volume, 4) +
   "}";
   
   string response;
   ApiPost("/ack", body, response);
}

//+------------------------------------------------------------------+
//| Poll Command                                                     |
//+------------------------------------------------------------------+
void PollCommand()
{
   string response;
   if(!ApiPost("/poll", "{}", response)) return;
   
   string command_id = JsonString(response, "id");
   string action = JsonString(response, "action");
   if(command_id == "" || action == "") return;
   
   long expires_epoch = (long)JsonNumber(response, "expires_epoch", 0);
   if(expires_epoch > 0 && TimeGMT() >= (datetime)expires_epoch) {
      SendAck(command_id, "rejected", 0, "Entry command expired before local execution");
      return;
   }
   
   string outcome = "rejected";
   string message = "Unsupported command";
   ulong ticket = 0;
   
   if(action == "ENTRY") {
      if(CommandWasExecuted(command_id)) {
         PositionByMagic(ticket);
         outcome = "executed";
         message = "Command already executed; restored from local journal";
      } else {
         outcome = ExecuteEntry(response, message, ticket);
      }
   } else if(action == "CLOSE") {
      ticket = (ulong)StringToInteger(JsonString(response, "ticket"));
      if(ticket == 0) ticket = (ulong)JsonNumber(response, "ticket", 0);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) {
         outcome = "executed";
         message = "Position already closed; idempotent confirmation";
      } else {
         bool requested = trade.PositionClose(ticket);
         message = trade.ResultRetcodeDescription();
         if(!requested || !TradeRequestAccepted()) {
            outcome = "failed";
         } else {
            Sleep(200);
            outcome = PositionSelectByTicket(ticket) ? "accepted" : "executed";
         }
      }
   }
   
   if(outcome == "executed") RememberExecutedCommand(command_id);
   SendAck(command_id, outcome, ticket, message);
}

//+------------------------------------------------------------------+
//| Initialize                                                       |
//+------------------------------------------------------------------+
int OnInit()
{
   init_attempts++;
   Print("========================================");
   Print("🚀 BTC Universal Bridge v", EaVersion, " initializing...");
   Print("   Attempt #", init_attempts);
   Print("   Time: ", TimeToString(TimeCurrent()));
   Print("   Account: ", AccountInfoInteger(ACCOUNT_LOGIN));
   Print("   Server: ", AccountInfoString(ACCOUNT_SERVER));
   Print("========================================");
   
   // Check Algo Trading
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED)) {
      Print("❌ Algo Trading is disabled!");
      Print("   Please enable: Tools → Options → Expert Advisors → Allow Algo Trading");
      return INIT_FAILED;
   }
   
   // Check WebRequest
   webrequest_ready = true;
   Print("🔍 Testing WebRequest to: ", BridgeUrl);
   string test_response;
   if(!ApiPost("/ping", "{}", test_response)) {
      Print("⚠️ WebRequest test failed. Please whitelist URL:");
      Print("   Tools → Options → Expert Advisors → Allow WebRequest");
      Print("   Add: ", BridgeUrl);
      webrequest_ready = false;
      // ✅ Don't fail — let EA run, just without API calls
   } else {
      Print("✅ WebRequest test passed!");
   }
   
   // Check Token
   if(BridgeToken == "" || BridgeToken == "PASTE-ONE-TIME-TOKEN") {
      Print("❌ Bridge token is not configured.");
      return INIT_PARAMETERS_INCORRECT;
   }
   
   // Detect Symbol
   Print("🔍 Detecting BTC symbol...");
   detected_symbol = DetectBTCSymbol();
   
   if(detected_symbol == "") {
      Print("❌ No BTC symbol found.");
      Print("   Please add BTCUSD or BTCUSDT to Market Watch (Ctrl+U)");
      Print("   Or set ManualSymbol input parameter");
      return INIT_FAILED;
   }
   
   // Symbol Info
   Print("✅ BTC symbol detected: ", detected_symbol);
   Print("   - Digits: ", SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS));
   Print("   - Spread: ", (SymbolInfoDouble(detected_symbol, SYMBOL_ASK) - SymbolInfoDouble(detected_symbol, SYMBOL_BID)) / SymbolInfoDouble(detected_symbol, SYMBOL_POINT));
   Print("   - Min Volume: ", SymbolInfoDouble(detected_symbol, SYMBOL_VOLUME_MIN));
   Print("   - Max Volume: ", SymbolInfoDouble(detected_symbol, SYMBOL_VOLUME_MAX));
   Print("   - Step: ", SymbolInfoDouble(detected_symbol, SYMBOL_VOLUME_STEP));
   
   // Initialize
   gv_prefix += (string)AccountInfoInteger(ACCOUNT_LOGIN) + "_" + (string)MagicNumber + "_";
   journal_file = "GPT_MT5_" + (string)AccountInfoInteger(ACCOUNT_LOGIN) + "_" + (string)MagicNumber + ".journal";
   
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(MaxDeviationPoints);
   
   // Set timer
   EventSetTimer(MathMax(1, PollSeconds));
   
   // Send initial heartbeat
   Print("📤 Sending initial heartbeat...");
   SendHeartbeat();
   
   Print("========================================");
   Print("✅ EA initialized successfully!");
   Print("   Symbol: ", detected_symbol);
   Print("   Magic: ", MagicNumber);
   Print("   Poll: ", PollSeconds, "s");
   Print("========================================");
   
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Deinitialize                                                     |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("========================================");
   Print("🛑 EA stopped. Reason: ", reason);
   Print("   Time: ", TimeToString(TimeCurrent()));
   Print("========================================");
}

//+------------------------------------------------------------------+
//| Timer                                                            |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Re-detect if symbol lost
   if(detected_symbol == "") {
      detected_symbol = DetectBTCSymbol();
      if(detected_symbol == "") return;
   }
   
   // Send heartbeat every 3 seconds
   SendHeartbeat();
   
   // Poll for commands every 3 seconds
   PollCommand();
}

//+------------------------------------------------------------------+
//| Tick - optional management                                       |
//+------------------------------------------------------------------+
void OnTick()
{
   // Tick-level management if needed
}

//+------------------------------------------------------------------+
//| End of EA                                                        |
//+------------------------------------------------------------------+