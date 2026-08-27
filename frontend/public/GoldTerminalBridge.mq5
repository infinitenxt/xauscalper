#property copyright "Gold Paper Terminal"
#property version   "1.00"
#property strict
#property description "XAU/USD-only bridge. New entries come from the authenticated API; open-position protection runs locally."

#include <Trade/Trade.mqh>

input string BridgeUrl = "https://YOUR-DOMAIN/api/mt5/bridge";
input string BridgeToken = "PASTE-ONE-TIME-TOKEN";
input string BrokerGoldSymbol = ""; // blank = discover XAUUSD/GOLD alias
input int PollSeconds = 3;
input ulong MagicNumber = 860081;
input int MaxDeviationPoints = 80;

CTrade trade;
string gold_symbol = "";
string gv_prefix = "GPT_MT5_";

string EscapeJson(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   return value;
}

bool IsGoldAlias(string symbol)
{
   string value = symbol;
   StringToUpper(value);
   StringReplace(value, "/", "");
   if(value == "XAUUSD" || value == "GOLD") return true;
   if(StringFind(value, "XAUUSD.") == 0 || StringFind(value, "XAUUSD_") == 0 || StringFind(value, "XAUUSD-") == 0) return true;
   if(StringFind(value, "GOLD.") == 0 || StringFind(value, "GOLD_") == 0 || StringFind(value, "GOLD-") == 0) return true;
   return false;
}

string ResolveGoldSymbol()
{
   if(BrokerGoldSymbol != "" && SymbolSelect(BrokerGoldSymbol, true) && IsGoldAlias(BrokerGoldSymbol))
      return BrokerGoldSymbol;
   int total = SymbolsTotal(false);
   for(int i = 0; i < total; i++)
   {
      string name = SymbolName(i, false);
      if(IsGoldAlias(name) && SymbolSelect(name, true)) return name;
   }
   total = SymbolsTotal(true);
   for(int i = 0; i < total; i++)
   {
      string name = SymbolName(i, true);
      if(IsGoldAlias(name)) return name;
   }
   return "";
}

bool ApiPost(string endpoint, string body, string &response)
{
   char data[];
   char result[];
   string response_headers;
   StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(data) > 0) ArrayResize(data, ArraySize(data) - 1);
   string headers = "Content-Type: application/json\r\nAuthorization: Bearer " + BridgeToken + "\r\n";
   ResetLastError();
   int status = WebRequest("POST", BridgeUrl + endpoint, headers, 8000, data, result, response_headers);
   response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(status < 200 || status >= 300)
   {
      Print("Bridge request failed: endpoint=", endpoint, " HTTP=", status, " error=", GetLastError(), " body=", response);
      return false;
   }
   return true;
}

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
   while(end < StringLen(json))
   {
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
   while(end < StringLen(json))
   {
      ushort c = (ushort)StringGetCharacter(json, end);
      if(!((c >= 48 && c <= 57) || c == 45 || c == 43 || c == 46 || c == 101 || c == 69)) break;
      end++;
   }
   string raw = StringSubstr(json, p, end - p);
   return raw == "" ? fallback : StringToDouble(raw);
}

bool PositionByMagic(ulong &ticket)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong current = PositionGetTicket(i);
      if(current == 0 || !PositionSelectByTicket(current)) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) == MagicNumber && PositionGetString(POSITION_SYMBOL) == gold_symbol)
      {
         ticket = current;
         return true;
      }
   }
   ticket = 0;
   return false;
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
   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
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
   return "[{\"ticket\":\"" + (string)ticket + "\",\"symbol\":\"" + EscapeJson(gold_symbol) +
      "\",\"direction\":\"" + direction + "\",\"volume\":" + DoubleToString(PositionGetDouble(POSITION_VOLUME), 4) +
      ",\"entry_price\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), (int)SymbolInfoInteger(gold_symbol, SYMBOL_DIGITS)) +
      ",\"current_price\":" + DoubleToString(PositionGetDouble(POSITION_PRICE_CURRENT), (int)SymbolInfoInteger(gold_symbol, SYMBOL_DIGITS)) +
      ",\"sl\":" + DoubleToString(PositionGetDouble(POSITION_SL), (int)SymbolInfoInteger(gold_symbol, SYMBOL_DIGITS)) +
      ",\"tp\":" + DoubleToString(PositionGetDouble(POSITION_TP), (int)SymbolInfoInteger(gold_symbol, SYMBOL_DIGITS)) +
      ",\"profit\":" + DoubleToString(PositionGetDouble(POSITION_PROFIT), 2) + "}]";
}

void SendHeartbeat()
{
   if(gold_symbol == "") gold_symbol = ResolveGoldSymbol();
   if(gold_symbol == "") return;
   bool demo = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO;
   string body = "{\"account_login\":\"" + (string)AccountInfoInteger(ACCOUNT_LOGIN) +
      "\",\"broker_server\":\"" + EscapeJson(AccountInfoString(ACCOUNT_SERVER)) +
      "\",\"is_demo\":" + (demo ? "true" : "false") +
      ",\"resolved_symbol\":\"" + EscapeJson(gold_symbol) +
      "\",\"balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) +
      ",\"equity\":" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) +
      ",\"free_margin\":" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) +
      ",\"daily_profit\":" + DoubleToString(DailyProfit(), 2) +
      ",\"volume_min\":" + DoubleToString(SymbolInfoDouble(gold_symbol, SYMBOL_VOLUME_MIN), 4) +
      ",\"volume_max\":" + DoubleToString(SymbolInfoDouble(gold_symbol, SYMBOL_VOLUME_MAX), 4) +
      ",\"volume_step\":" + DoubleToString(SymbolInfoDouble(gold_symbol, SYMBOL_VOLUME_STEP), 4) +
      ",\"trade_allowed\":" + (AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) ? "true" : "false") +
      ",\"algo_trading\":" + (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED) ? "true" : "false") +
      ",\"terminal_build\":" + (string)TerminalInfoInteger(TERMINAL_BUILD) +
      ",\"positions\":" + PositionJson() + "}";
   string response;
   ApiPost("/heartbeat", body, response);
}

bool ValidVolume(double lots, string &message)
{
   double vmin = SymbolInfoDouble(gold_symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(gold_symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(gold_symbol, SYMBOL_VOLUME_STEP);
   if(lots < vmin || lots > vmax) { message = "lot outside broker min/max"; return false; }
   double steps = (lots - vmin) / step;
   if(MathAbs(steps - MathRound(steps)) > 0.000001) { message = "lot does not match broker step"; return false; }
   return true;
}

void SaveManagement(double entry, double sl, string json)
{
   GlobalVariableSet(gv_prefix + "entry", entry);
   GlobalVariableSet(gv_prefix + "risk", MathAbs(entry - sl));
   GlobalVariableSet(gv_prefix + "opened", (double)TimeCurrent());
   GlobalVariableSet(gv_prefix + "maxhold", JsonNumber(json, "max_hold_seconds", 900));
   GlobalVariableSet(gv_prefix + "be", JsonNumber(json, "breakeven_at_r", 0.8));
   GlobalVariableSet(gv_prefix + "partialr", JsonNumber(json, "partial_tp_at_r", 1.0));
   GlobalVariableSet(gv_prefix + "partialfraction", JsonNumber(json, "partial_tp_fraction", 0.5));
   GlobalVariableSet(gv_prefix + "partialdone", 0.0);
   GlobalVariableSet(gv_prefix + "trailr", JsonNumber(json, "trail_start_r", 1.0));
   GlobalVariableSet(gv_prefix + "traildistance", JsonNumber(json, "trail_distance", 0.0));
}

bool ExecuteEntry(string json, string &message, ulong &ticket)
{
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED) || !AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
   { message = "trading or Algo Trading is disabled"; return false; }
   ulong existing;
   if(PositionByMagic(existing)) { ticket = existing; message = "entry already executed; idempotent confirmation"; return true; }
   string side = JsonString(json, "direction");
   double lots = JsonNumber(json, "lots");
   double sl = JsonNumber(json, "sl");
   double tp = JsonNumber(json, "tp");
   double atr = JsonNumber(json, "atr");
   if(!ValidVolume(lots, message)) return false;
   ENUM_ORDER_TYPE type = side == "BUY" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double price = side == "BUY" ? SymbolInfoDouble(gold_symbol, SYMBOL_ASK) : SymbolInfoDouble(gold_symbol, SYMBOL_BID);
   double spread = SymbolInfoDouble(gold_symbol, SYMBOL_ASK) - SymbolInfoDouble(gold_symbol, SYMBOL_BID);
   if(atr > 0 && spread > atr * 0.15) { message = "spread exceeds 15% of ATR"; return false; }
   if((side == "BUY" && !(sl < price && tp > price)) || (side == "SELL" && !(sl > price && tp < price)))
   { message = "SL/TP direction is invalid"; return false; }
   if((ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(gold_symbol, SYMBOL_TRADE_MODE) != SYMBOL_TRADE_MODE_FULL)
   { message = "broker has not enabled full trading for the gold symbol"; return false; }
   double margin = 0.0;
   if(!OrderCalcMargin(type, gold_symbol, lots, price, margin) || margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
   { message = "insufficient free margin"; return false; }
   int stops = (int)SymbolInfoInteger(gold_symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double point = SymbolInfoDouble(gold_symbol, SYMBOL_POINT);
   if(sl <= 0 || tp <= 0 || MathAbs(price - sl) < stops * point || MathAbs(price - tp) < stops * point)
   { message = "SL/TP violates broker stop distance"; return false; }
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(MaxDeviationPoints);
   trade.SetTypeFillingBySymbol(gold_symbol);
   bool ok = side == "BUY" ? trade.Buy(lots, gold_symbol, 0.0, sl, tp, "GPT bridge") : trade.Sell(lots, gold_symbol, 0.0, sl, tp, "GPT bridge");
   message = trade.ResultRetcodeDescription();
   if(!ok) return false;
   Sleep(200);
   if(PositionByMagic(ticket) && PositionSelectByTicket(ticket))
      SaveManagement(PositionGetDouble(POSITION_PRICE_OPEN), sl, json);
   return ticket > 0;
}

void SendAck(string command_id, bool success, ulong ticket, string message)
{
   double price = 0.0, volume = 0.0;
   if(ticket > 0 && PositionSelectByTicket(ticket))
   {
      price = PositionGetDouble(POSITION_PRICE_OPEN);
      volume = PositionGetDouble(POSITION_VOLUME);
   }
   string body = "{\"command_id\":\"" + EscapeJson(command_id) + "\",\"success\":" + (success ? "true" : "false") +
      ",\"broker_ticket\":" + (ticket > 0 ? "\"" + (string)ticket + "\"" : "null") +
      ",\"broker_message\":\"" + EscapeJson(message) + "\",\"filled_price\":" + DoubleToString(price, 5) +
      ",\"filled_volume\":" + DoubleToString(volume, 4) + "}";
   string response;
   ApiPost("/ack", body, response);
}

void PollCommand()
{
   string response;
   if(!ApiPost("/poll", "{}", response)) return;
   string command_id = JsonString(response, "id");
   string action = JsonString(response, "action");
   if(command_id == "" || action == "") return;
   bool success = false;
   string message = "unsupported command";
   ulong ticket = 0;
   if(action == "ENTRY") success = ExecuteEntry(response, message, ticket);
   else if(action == "CLOSE")
   {
      ticket = (ulong)StringToInteger(JsonString(response, "ticket"));
      if(ticket == 0) ticket = (ulong)JsonNumber(response, "ticket", 0);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) { success = true; message = "position already closed; idempotent confirmation"; }
      else { success = trade.PositionClose(ticket); message = trade.ResultRetcodeDescription(); }
   }
   SendAck(command_id, success, ticket, message);
}

void ManageOpenPosition()
{
   ulong ticket;
   if(!PositionByMagic(ticket) || !PositionSelectByTicket(ticket)) return;
   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   double current = PositionGetDouble(POSITION_PRICE_CURRENT);
   double sl = PositionGetDouble(POSITION_SL);
   double tp = PositionGetDouble(POSITION_TP);
   double volume = PositionGetDouble(POSITION_VOLUME);
   bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
   double risk = GlobalVariableGet(gv_prefix + "risk");
   if(risk <= 0) risk = MathAbs(entry - sl);
   if(risk <= 0) return;
   double favorable = (current - entry) * (buy ? 1.0 : -1.0);
   double r = favorable / risk;
   datetime opened = (datetime)GlobalVariableGet(gv_prefix + "opened");
   int maxhold = (int)GlobalVariableGet(gv_prefix + "maxhold");
   if(maxhold > 0 && opened > 0 && TimeCurrent() - opened >= maxhold)
   {
      trade.PositionClose(ticket);
      return;
   }
   double partial_r = GlobalVariableGet(gv_prefix + "partialr");
   double fraction = GlobalVariableGet(gv_prefix + "partialfraction");
   if(GlobalVariableGet(gv_prefix + "partialdone") < 0.5 && fraction > 0 && fraction < 1 && r >= partial_r)
   {
      double vmin = SymbolInfoDouble(gold_symbol, SYMBOL_VOLUME_MIN);
      double step = SymbolInfoDouble(gold_symbol, SYMBOL_VOLUME_STEP);
      double close_volume = MathFloor((volume * fraction) / step) * step;
      if(close_volume >= vmin && volume - close_volume >= vmin && trade.PositionClosePartial(ticket, close_volume))
         GlobalVariableSet(gv_prefix + "partialdone", 1.0);
   }
   double be_r = GlobalVariableGet(gv_prefix + "be");
   if(r >= be_r)
   {
      double be = entry + (buy ? 0.05 * risk : -0.05 * risk);
      if((buy && (sl == 0 || be > sl)) || (!buy && (sl == 0 || be < sl)))
      {
         if(trade.PositionModify(ticket, be, tp)) sl = be;
      }
   }
   double trail_r = GlobalVariableGet(gv_prefix + "trailr");
   double trail_distance = GlobalVariableGet(gv_prefix + "traildistance");
   if(r >= trail_r && trail_distance > 0)
   {
      double candidate = current + (buy ? -trail_distance : trail_distance);
      double floor_stop = entry + (buy ? 0.3 * risk : -0.3 * risk);
      double next_sl = buy ? MathMax(candidate, floor_stop) : MathMin(candidate, floor_stop);
      if((buy && next_sl > sl) || (!buy && (sl == 0 || next_sl < sl))) trade.PositionModify(ticket, next_sl, tp);
   }
}

int OnInit()
{
   if(BridgeToken == "" || BridgeToken == "PASTE-ONE-TIME-TOKEN")
   {
      Print("Bridge token is not configured.");
      return INIT_PARAMETERS_INCORRECT;
   }
   gold_symbol = ResolveGoldSymbol();
   if(gold_symbol == "")
   {
      Print("No approved XAU/USD symbol alias was found.");
      return INIT_FAILED;
   }
   gv_prefix += (string)AccountInfoInteger(ACCOUNT_LOGIN) + "_" + (string)MagicNumber + "_";
   trade.SetExpertMagicNumber(MagicNumber);
   EventSetTimer(MathMax(1, PollSeconds));
   SendHeartbeat();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   ManageOpenPosition();
   SendHeartbeat();
   PollCommand();
}

void OnTick()
{
   ManageOpenPosition();
}