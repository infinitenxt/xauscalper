//+------------------------------------------------------------------+
//|                                      Universal_Asset_Bridge.mq5   |
//|                 Universal BTC/USD + XAU/USD Bridge for MT5       |
//|                                                                  |
//| Supports broker symbol variants such as:                         |
//| BTCUSD, BTCUSD.p, BTCUSDm, BTCUSDT, XBTUSD, etc.                |
//| XAUUSD, XAUUSD.p, XAUUSDm, GOLD, GOLD.p, etc.                   |
//+------------------------------------------------------------------+
#property copyright "Universal Asset Bridge"
#property version   "4.4"
#property strict
#property description "Universal BTC/XAU bridge - auto-detects broker symbol variants"
#property description "Supports BTCUSD/BTCUSDT/XBT and XAUUSD/GOLD variants"
#property description "Uses actual broker symbol for trading"

#include <Trade/Trade.mqh>

//====================================================================
// INPUTS
//====================================================================

input string BridgeUrl = "https://trade.infinitenxt.com/api/mt5/bridge";
input string BridgeToken = "PASTE_YOUR_TOKEN";

// Leave empty for automatic detection.
// If filled, EA will use this exact symbol if it belongs to BTC/XAU family.
input string ManualSymbol = "";

// Prefer the symbol of the chart where EA is attached.
input bool PreferChartSymbol = true;

input int PollSeconds = 3;
input ulong MagicNumber = 860081;
input int MaxDeviationPoints = 80;

input string EaVersion = "4.4";

//====================================================================
// GLOBALS
//====================================================================

CTrade trade;

string gv_prefix = "GPT_MT5_";
string journal_file = "";

string detected_symbol = "";
string detected_asset = "";       // BTC or XAU

bool webrequest_ready = false;

datetime last_heartbeat = 0;
datetime last_poll = 0;
bool market_history_synced = false;
int market_sync_step = 0;

int init_attempts = 0;


//====================================================================
// BTC PATTERNS
//====================================================================

string BTC_EXACT_PATTERNS[] =
{
   "BTCUSD",
   "BTCUSDT",
   "XBTUSD",
   "XBTUSDT",
   "BTC/USD",
   "BTC/USDT",
   "XBT/USD",
   "XBT/USDT",
   "BTC",
   "BITCOIN",
   "BTCSPOT",
   "BTC.CMD"
};


//====================================================================
// XAU / GOLD EXACT PATTERNS
//====================================================================

string XAU_EXACT_PATTERNS[] =
{
   "XAUUSD",
   "XAU/USD",
   "GOLD",
   "GOLDUSD",
   "XAU",
   "XAU.SPOT",
   "GOLDSPOT",
   "GOLD.CMD"
};


//====================================================================
// ESCAPE JSON
//====================================================================

string EscapeJson(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\r", "\\r");

   return value;
}


//====================================================================
// NORMALIZE SYMBOL
//====================================================================

string NormalizeSymbol(string symbol)
{
   string upper = symbol;

   StringToUpper(upper);

   StringReplace(upper, "/", "");
   StringReplace(upper, ".", "");
   StringReplace(upper, "_", "");
   StringReplace(upper, "-", "");
   StringReplace(upper, ":", "");
   StringReplace(upper, " ", "");

   return upper;
}


//====================================================================
// CHECK BTC SYMBOL
//====================================================================

bool IsBTCSymbol(string symbol)
{
   if(symbol == "")
      return false;

   string upper = NormalizeSymbol(symbol);

   // ---------------------------------------------------------------
   // Exact / normalized patterns
   // ---------------------------------------------------------------

   for(int i = 0; i < ArraySize(BTC_EXACT_PATTERNS); i++)
   {
      string pattern = NormalizeSymbol(BTC_EXACT_PATTERNS[i]);

      if(upper == pattern)
         return true;
   }

   // ---------------------------------------------------------------
   // BTC + USD / USDT
   //
   // Examples:
   // BTCUSD
   // BTCUSDp
   // BTCUSDm
   // BTCUSDpro
   // BTCUSDT
   // BTCUSD.c
   // mBTCUSD
   // ---------------------------------------------------------------

   int btc_pos = StringFind(upper, "BTC");

   if(btc_pos >= 0)
   {
      bool has_usd =
         StringFind(upper, "USD") >= 0 ||
         StringFind(upper, "USDT") >= 0;

      if(has_usd)
      {
         // Exclude common unrelated instruments containing BTC
         if(StringFind(upper, "GBTC") < 0 &&
            StringFind(upper, "EBTC") < 0 &&
            StringFind(upper, "SBTC") < 0)
         {
            return true;
         }
      }
   }

   // ---------------------------------------------------------------
   // XBT + USD / USDT
   // ---------------------------------------------------------------

   int xbt_pos = StringFind(upper, "XBT");

   if(xbt_pos >= 0)
   {
      bool has_usd =
         StringFind(upper, "USD") >= 0 ||
         StringFind(upper, "USDT") >= 0;

      if(has_usd)
         return true;
   }

   return false;
}


//====================================================================
// CHECK XAU / GOLD SYMBOL
//====================================================================

bool IsXAUSymbol(string symbol)
{
   if(symbol == "")
      return false;

   string upper = NormalizeSymbol(symbol);

   // ---------------------------------------------------------------
   // Exact / normalized patterns
   // ---------------------------------------------------------------

   for(int i = 0; i < ArraySize(XAU_EXACT_PATTERNS); i++)
   {
      string pattern = NormalizeSymbol(XAU_EXACT_PATTERNS[i]);

      if(upper == pattern)
         return true;
   }

   // ---------------------------------------------------------------
   // XAU based variants
   //
   // XAUUSD
   // XAUUSDp
   // XAUUSDm
   // mXAUUSD
   // XAUUSDpro
   // XAU/USD
   // ---------------------------------------------------------------

   if(StringFind(upper, "XAU") >= 0)
   {
      bool has_usd = StringFind(upper, "USD") >= 0;

      if(has_usd)
         return true;

      // XAU by itself can also be a broker symbol.
      if(StringLen(upper) <= 10)
         return true;
   }

   // ---------------------------------------------------------------
   // GOLD variants
   //
   // GOLD
   // GOLDp
   // GOLDm
   // GOLDUSD
   // mGOLD
   // ---------------------------------------------------------------

   if(StringFind(upper, "GOLD") >= 0)
   {
      return true;
   }

   return false;
}


//====================================================================
// GET ASSET FAMILY
//====================================================================

string GetAssetFamily(string symbol)
{
   if(IsBTCSymbol(symbol))
      return "BTC";

   if(IsXAUSymbol(symbol))
      return "XAU";

   return "";
}


//====================================================================
// CHECK IF SYMBOL IS SUPPORTED
//====================================================================

bool IsSupportedSymbol(string symbol)
{
   return GetAssetFamily(symbol) != "";
}


//====================================================================
// SELECT SYMBOL SAFELY
//====================================================================

bool SelectSymbol(string symbol)
{
   if(symbol == "")
      return false;

   ResetLastError();

   if(SymbolSelect(symbol, true))
      return true;

   Print("⚠️ Could not select symbol: ", symbol,
         " error=", GetLastError());

   return false;
}


//====================================================================
// DETECT SYMBOL
//====================================================================

string DetectUniversalSymbol()
{
   Print("🔍 Searching for supported BTC/XAU symbol...");

   // ---------------------------------------------------------------
   // 1. Manual symbol
   // ---------------------------------------------------------------

   if(ManualSymbol != "")
   {
      if(SelectSymbol(ManualSymbol) &&
         IsSupportedSymbol(ManualSymbol))
      {
         detected_asset = GetAssetFamily(ManualSymbol);

         Print("✅ Using manual symbol: ",
               ManualSymbol,
               " [",
               detected_asset,
               "]");

         return ManualSymbol;
      }

      Print("⚠️ ManualSymbol is invalid or unsupported: ",
            ManualSymbol);
   }


   // ---------------------------------------------------------------
   // 2. Prefer current chart symbol
   // ---------------------------------------------------------------

   if(PreferChartSymbol)
   {
      string chart_symbol = _Symbol;

      if(IsSupportedSymbol(chart_symbol))
      {
         if(SelectSymbol(chart_symbol))
         {
            detected_asset = GetAssetFamily(chart_symbol);

            Print("✅ Using chart symbol: ",
                  chart_symbol,
                  " [",
                  detected_asset,
                  "]");

            return chart_symbol;
         }
      }
   }


   // ---------------------------------------------------------------
   // 3. Search Market Watch
   // ---------------------------------------------------------------

   int total = SymbolsTotal(false);

   for(int i = 0; i < total; i++)
   {
      string name = SymbolName(i, false);

      if(IsSupportedSymbol(name))
      {
         if(SelectSymbol(name))
         {
            detected_asset = GetAssetFamily(name);

            Print("✅ Detected supported symbol in Market Watch: ",
                  name,
                  " [",
                  detected_asset,
                  "]");

            return name;
         }
      }
   }


   // ---------------------------------------------------------------
   // 4. Search all symbols
   // ---------------------------------------------------------------

   total = SymbolsTotal(true);

   for(int i = 0; i < total; i++)
   {
      string name = SymbolName(i, true);

      if(IsSupportedSymbol(name))
      {
         if(SelectSymbol(name))
         {
            detected_asset = GetAssetFamily(name);

            Print("✅ Detected supported symbol in All Symbols: ",
                  name,
                  " [",
                  detected_asset,
                  "]");

            return name;
         }
      }
   }


   // ---------------------------------------------------------------
   // 5. Direct common-symbol fallback
   // ---------------------------------------------------------------

   string common_symbols[] =
   {
      "BTCUSD",
      "BTCUSDT",
      "XBTUSD",
      "XAUUSD",
      "GOLD"
   };

   for(int i = 0; i < ArraySize(common_symbols); i++)
   {
      if(SelectSymbol(common_symbols[i]))
      {
         if(IsSupportedSymbol(common_symbols[i]))
         {
            detected_asset = GetAssetFamily(common_symbols[i]);

            Print("✅ Found common symbol: ",
                  common_symbols[i],
                  " [",
                  detected_asset,
                  "]");

            return common_symbols[i];
         }
      }
   }


   Print("❌ No supported BTC/XAU symbol found.");

   return "";
}


//====================================================================
// HTTP POST
//====================================================================

bool ApiPost(string endpoint,
             string body,
             string &response)
{
   // Keep retrying WebRequest on every timer cycle. A transient /ping
   // failure must never permanently disable heartbeat/polling.
   char data[];
   char result[];

   string response_headers;

   StringToCharArray(
      body,
      data,
      0,
      WHOLE_ARRAY,
      CP_UTF8
   );

   if(ArraySize(data) > 0)
      ArrayResize(data, ArraySize(data) - 1);

   string headers =
      "Content-Type: application/json\r\n"
      "Authorization: Bearer " + BridgeToken + "\r\n";

   ResetLastError();

   int status = WebRequest(
      "POST",
      BridgeUrl + endpoint,
      headers,
      8000,
      data,
      result,
      response_headers
   );

   response =
      CharArrayToString(
         result,
         0,
         WHOLE_ARRAY,
         CP_UTF8
      );

   if(status < 200 || status >= 300)
   {
      int request_error = GetLastError();

      Print(
         "❌ Bridge request failed: endpoint=",
         endpoint,
         " HTTP=",
         status,
         " error=",
         request_error
      );

      if(response != "")
      {
         Print(
            "   Backend response: ",
            response
         );
      }

      if(status == 0)
      {
         Print("⚠️ HTTP 0 means WebRequest may be blocked or unreachable.");
         Print("   MT5 Tools → Options → Expert Advisors →");
         Print("   Allow WebRequest for listed URL:");
         Print("   ", BridgeUrl);
      }

      return false;
   }

   return true;
}


//====================================================================
// JSON STRING
//====================================================================

string JsonString(string json,
                  string key)
{
   string marker = "\"" + key + "\"";

   int p = StringFind(json, marker);

   if(p < 0)
      return "";

   p = StringFind(
      json,
      ":",
      p + StringLen(marker)
   );

   if(p < 0)
      return "";

   p++;

   while(
      p < StringLen(json) &&
      StringGetCharacter(json, p) <= 32
   )
   {
      p++;
   }

   if(StringSubstr(json, p, 4) == "null")
      return "";

   if(StringGetCharacter(json, p) != 34)
      return "";

   p++;

   int end = p;

   while(end < StringLen(json))
   {
      if(
         StringGetCharacter(json, end) == 34 &&
         (
            end == p ||
            StringGetCharacter(json, end - 1) != 92
         )
      )
      {
         break;
      }

      end++;
   }

   return StringSubstr(
      json,
      p,
      end - p
   );
}


//====================================================================
// JSON NUMBER
//====================================================================

double JsonNumber(string json,
                  string key,
                  double fallback = 0.0)
{
   string marker = "\"" + key + "\"";

   int p = StringFind(json, marker);

   if(p < 0)
      return fallback;

   p = StringFind(
      json,
      ":",
      p + StringLen(marker)
   );

   if(p < 0)
      return fallback;

   p++;

   while(
      p < StringLen(json) &&
      StringGetCharacter(json, p) <= 32
   )
   {
      p++;
   }

   int end = p;

   while(end < StringLen(json))
   {
      ushort c =
         (ushort)StringGetCharacter(json, end);

      if(!(
         (c >= 48 && c <= 57) ||
         c == 45 ||
         c == 43 ||
         c == 46 ||
         c == 101 ||
         c == 69
      ))
      {
         break;
      }

      end++;
   }

   string raw =
      StringSubstr(
         json,
         p,
         end - p
      );

   return raw == ""
      ? fallback
      : StringToDouble(raw);
}


//====================================================================
// POSITION BY MAGIC + CURRENT SYMBOL
//====================================================================

bool PositionByMagic(ulong &ticket)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong current =
         PositionGetTicket(i);

      if(current == 0)
         continue;

      if(!PositionSelectByTicket(current))
         continue;

      ulong magic =
         (ulong)PositionGetInteger(
            POSITION_MAGIC
         );

      string symbol =
         PositionGetString(
            POSITION_SYMBOL
         );

      if(
         magic == MagicNumber &&
         symbol == detected_symbol
      )
      {
         ticket = current;

         return true;
      }
   }

   ticket = 0;

   return false;
}


//====================================================================
// TRADE RESULT CHECK
//====================================================================

bool TradeRequestAccepted()
{
   uint code = trade.ResultRetcode();

   return
      code == TRADE_RETCODE_DONE ||
      code == TRADE_RETCODE_DONE_PARTIAL ||
      code == TRADE_RETCODE_PLACED;
}


//====================================================================
// LOCAL POSITION MANAGEMENT STATE
//====================================================================

void SaveManagementState(string json, ulong ticket, double initial_risk)
{
   if(!PositionSelectByTicket(ticket))
      return;

   double trail_distance = JsonNumber(json, "trail_distance", 0.0);
   if(trail_distance <= 0.0)
      trail_distance = initial_risk * 0.60;

   GlobalVariableSet(gv_prefix + "entry", PositionGetDouble(POSITION_PRICE_OPEN));
   GlobalVariableSet(gv_prefix + "risk", initial_risk);
   GlobalVariableSet(gv_prefix + "opened", (double)PositionGetInteger(POSITION_TIME));
   GlobalVariableSet(gv_prefix + "maxhold", JsonNumber(json, "max_hold_seconds", 1200.0));
   GlobalVariableSet(gv_prefix + "trailenabled", JsonNumber(json, "trailing_enabled", 1.0));
   GlobalVariableSet(gv_prefix + "trailstart", JsonNumber(json, "trail_start_r", 0.80));
   GlobalVariableSet(gv_prefix + "traildistance", trail_distance);
   GlobalVariableSet(gv_prefix + "profitlock", JsonNumber(json, "profit_lock_r", 0.10));
}


void EnsureManagementState(ulong ticket)
{
   if(!PositionSelectByTicket(ticket))
      return;

   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   double current_sl = PositionGetDouble(POSITION_SL);
   double risk = MathAbs(entry - current_sl);

   if(!GlobalVariableCheck(gv_prefix + "entry")) GlobalVariableSet(gv_prefix + "entry", entry);
   if(!GlobalVariableCheck(gv_prefix + "risk")) GlobalVariableSet(gv_prefix + "risk", risk);
   if(!GlobalVariableCheck(gv_prefix + "opened")) GlobalVariableSet(gv_prefix + "opened", (double)PositionGetInteger(POSITION_TIME));
   if(!GlobalVariableCheck(gv_prefix + "maxhold")) GlobalVariableSet(gv_prefix + "maxhold", 1200.0);
   if(!GlobalVariableCheck(gv_prefix + "trailenabled")) GlobalVariableSet(gv_prefix + "trailenabled", 1.0);
   if(!GlobalVariableCheck(gv_prefix + "trailstart")) GlobalVariableSet(gv_prefix + "trailstart", 0.80);
   if(!GlobalVariableCheck(gv_prefix + "traildistance")) GlobalVariableSet(gv_prefix + "traildistance", risk * 0.60);
   if(!GlobalVariableCheck(gv_prefix + "profitlock")) GlobalVariableSet(gv_prefix + "profitlock", 0.10);
}


void ManageOpenPosition()
{
   ulong ticket = 0;
   if(!PositionByMagic(ticket) || !PositionSelectByTicket(ticket))
      return;

   EnsureManagementState(ticket);

   datetime opened = (datetime)GlobalVariableGet(gv_prefix + "opened");
   int max_hold = (int)GlobalVariableGet(gv_prefix + "maxhold");
   if(max_hold > 0 && opened > 0 && (TimeCurrent() - opened) >= max_hold)
   {
      if(trade.PositionClose(ticket))
         Print("✅ Hard autocut closed ticket ", ticket, " after ", max_hold, " seconds");
      else
         Print("❌ Hard autocut failed: ", trade.ResultRetcodeDescription());
      return;
   }

   if(GlobalVariableGet(gv_prefix + "trailenabled") < 0.5)
      return;

   double entry = GlobalVariableGet(gv_prefix + "entry");
   double risk = GlobalVariableGet(gv_prefix + "risk");
   double trail_start = GlobalVariableGet(gv_prefix + "trailstart");
   double trail_distance = GlobalVariableGet(gv_prefix + "traildistance");
   double profit_lock = GlobalVariableGet(gv_prefix + "profitlock");
   if(entry <= 0.0 || risk <= 0.0 || trail_distance <= 0.0)
      return;

   ENUM_POSITION_TYPE position_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   bool is_buy = position_type == POSITION_TYPE_BUY;
   double current = SymbolInfoDouble(detected_symbol, is_buy ? SYMBOL_BID : SYMBOL_ASK);
   double favorable = (current - entry) * (is_buy ? 1.0 : -1.0);
   if(favorable / risk < trail_start)
      return;

   double current_sl = PositionGetDouble(POSITION_SL);
   double tp = PositionGetDouble(POSITION_TP);
   double candidate = is_buy ? current - trail_distance : current + trail_distance;
   double floor_sl = is_buy ? entry + risk * profit_lock : entry - risk * profit_lock;
   double next_sl = is_buy ? MathMax(candidate, floor_sl) : MathMin(candidate, floor_sl);

   double point = SymbolInfoDouble(detected_symbol, SYMBOL_POINT);
   int stops = (int)SymbolInfoInteger(detected_symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double minimum_distance = stops * point;
   next_sl = is_buy ? MathMin(next_sl, current - minimum_distance) : MathMax(next_sl, current + minimum_distance);
   next_sl = NormalizeDouble(next_sl, (int)SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS));

   bool improves = is_buy ? (next_sl > current_sl + point) : (current_sl <= 0.0 || next_sl < current_sl - point);
   if(!improves || next_sl <= 0.0)
      return;

   if(!trade.PositionModify(ticket, next_sl, tp))
      Print("❌ Trailing stop modify failed: ", trade.ResultRetcodeDescription());
}


//====================================================================
// COMMAND JOURNAL
//====================================================================

bool CommandWasExecuted(string command_id)
{
   int handle =
      FileOpen(
         journal_file,
         FILE_READ |
         FILE_TXT |
         FILE_ANSI |
         FILE_SHARE_READ |
         FILE_SHARE_WRITE
      );

   if(handle == INVALID_HANDLE)
      return false;

   bool found = false;

   while(!FileIsEnding(handle))
   {
      string line =
         FileReadString(handle);

      if(line == command_id)
      {
         found = true;
         break;
      }
   }

   FileClose(handle);

   return found;
}


//====================================================================
// REMEMBER COMMAND
//====================================================================

void RememberExecutedCommand(string command_id)
{
   if(command_id == "")
      return;

   if(CommandWasExecuted(command_id))
      return;

   int handle =
      FileOpen(
         journal_file,
         FILE_READ |
         FILE_WRITE |
         FILE_TXT |
         FILE_ANSI |
         FILE_SHARE_READ
      );

   if(handle == INVALID_HANDLE)
   {
      handle =
         FileOpen(
            journal_file,
            FILE_WRITE |
            FILE_TXT |
            FILE_ANSI |
            FILE_SHARE_READ
         );
   }

   if(handle == INVALID_HANDLE)
   {
      Print(
         "❌ Could not persist command journal. Error: ",
         GetLastError()
      );

      return;
   }

   FileSeek(
      handle,
      0,
      SEEK_END
   );

   FileWrite(
      handle,
      command_id
   );

   FileFlush(handle);

   FileClose(handle);
}


//====================================================================
// DAILY PROFIT
//====================================================================

double DailyProfit()
{
   MqlDateTime parts;

   TimeToStruct(
      TimeCurrent(),
      parts
   );

   parts.hour = 0;
   parts.min  = 0;
   parts.sec  = 0;

   datetime start =
      StructToTime(parts);

   if(!HistorySelect(
      start,
      TimeCurrent()
   ))
   {
      return 0.0;
   }

   double result = 0.0;

   int total =
      HistoryDealsTotal();

   for(int i = 0; i < total; i++)
   {
      ulong ticket =
         HistoryDealGetTicket(i);

      if(ticket == 0)
         continue;

      ENUM_DEAL_TYPE type =
         (ENUM_DEAL_TYPE)
         HistoryDealGetInteger(
            ticket,
            DEAL_TYPE
         );

      if(
         type != DEAL_TYPE_BUY &&
         type != DEAL_TYPE_SELL
      )
      {
         continue;
      }

      result +=
         HistoryDealGetDouble(
            ticket,
            DEAL_PROFIT
         );

      result +=
         HistoryDealGetDouble(
            ticket,
            DEAL_SWAP
         );

      result +=
         HistoryDealGetDouble(
            ticket,
            DEAL_COMMISSION
         );
   }

   return result;
}


//====================================================================
// POSITION JSON
//====================================================================

string PositionJson()
{
   ulong ticket;

   if(
      !PositionByMagic(ticket) ||
      !PositionSelectByTicket(ticket)
   )
   {
      return "[]";
   }

   string direction =
      PositionGetInteger(POSITION_TYPE)
      == POSITION_TYPE_BUY
      ? "BUY"
      : "SELL";

   int digits =
      (int)SymbolInfoInteger(
         detected_symbol,
         SYMBOL_DIGITS
      );

   return
      "[{\"ticket\":\"" +
      (string)ticket +

      "\",\"symbol\":\"" +
      EscapeJson(detected_symbol) +

      "\",\"asset\":\"" +
      EscapeJson(detected_asset) +

      "\",\"direction\":\"" +
      direction +

      "\",\"volume\":" +
      DoubleToString(
         PositionGetDouble(POSITION_VOLUME),
         4
      ) +

      ",\"entry_price\":" +
      DoubleToString(
         PositionGetDouble(
            POSITION_PRICE_OPEN
         ),
         digits
      ) +

      ",\"current_price\":" +
      DoubleToString(
         PositionGetDouble(
            POSITION_PRICE_CURRENT
         ),
         digits
      ) +

      ",\"sl\":" +
      DoubleToString(
         PositionGetDouble(POSITION_SL),
         digits
      ) +

      ",\"tp\":" +
      DoubleToString(
         PositionGetDouble(POSITION_TP),
         digits
      ) +

      ",\"profit\":" +
      DoubleToString(
         PositionGetDouble(POSITION_PROFIT),
         2
      ) +

      ",\"opened_at\":" +
      (string)
      PositionGetInteger(
         POSITION_TIME
      ) +

      "}]";
}


//====================================================================
// BROKER MARKET DATA RELAY
//====================================================================

void AppendRates(string &json, bool &first, ENUM_TIMEFRAMES period, string timeframe, int duration_seconds, int count)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(detected_symbol, period, 1, count, rates);
   if(copied <= 0) return;
   int digits = (int)SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS);
   for(int i = 0; i < copied; i++)
   {
      if(!first) json += ",";
      first = false;
      json += "{\"timeframe\":\"" + timeframe + "\"" +
              ",\"open_time\":" + IntegerToString((long)rates[i].time) +
              ",\"duration_seconds\":" + (string)duration_seconds +
              ",\"open\":" + DoubleToString(rates[i].open, digits) +
              ",\"high\":" + DoubleToString(rates[i].high, digits) +
              ",\"low\":" + DoubleToString(rates[i].low, digits) +
              ",\"close\":" + DoubleToString(rates[i].close, digits) +
              ",\"tick_volume\":" + (string)rates[i].tick_volume +
              ",\"spread_points\":" + (string)rates[i].spread + "}";
   }
}


void SendMarketData()
{
   if(detected_symbol == "") return;
   double bid = SymbolInfoDouble(detected_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(detected_symbol, SYMBOL_ASK);
   double point = SymbolInfoDouble(detected_symbol, SYMBOL_POINT);
   if(bid <= 0.0 || ask <= 0.0 || point <= 0.0) return;

   int count = market_history_synced ? 2 : 80;
   string bars = "[";
   bool first = true;
   if(market_history_synced)
   {
      AppendRates(bars, first, PERIOD_M1,  "1m",  60,   count);
      AppendRates(bars, first, PERIOD_M5,  "5m",  300,  count);
      AppendRates(bars, first, PERIOD_M15, "15m", 900,  count);
      AppendRates(bars, first, PERIOD_M30, "30m", 1800, count);
      AppendRates(bars, first, PERIOD_H1,  "1h",  3600, count);
   }
   else if(market_sync_step == 0) AppendRates(bars, first, PERIOD_M1,  "1m",  60,   count);
   else if(market_sync_step == 1) AppendRates(bars, first, PERIOD_M5,  "5m",  300,  count);
   else if(market_sync_step == 2) AppendRates(bars, first, PERIOD_M15, "15m", 900,  count);
   else if(market_sync_step == 3) AppendRates(bars, first, PERIOD_M30, "30m", 1800, count);
   else AppendRates(bars, first, PERIOD_H1, "1h", 3600, count);
   bars += "]";

   int digits = (int)SymbolInfoInteger(detected_symbol, SYMBOL_DIGITS);
   double spread_points = (ask - bid) / point;
   string body = "{\"symbol\":\"" + EscapeJson(detected_symbol) + "\"" +
      ",\"broker_day\":\"" + TimeToString(TimeCurrent(), TIME_DATE) + "\"" +
      ",\"bid\":" + DoubleToString(bid, digits) +
      ",\"ask\":" + DoubleToString(ask, digits) +
      ",\"tick_time\":" + IntegerToString((long)TimeCurrent()) +
      ",\"point\":" + DoubleToString(point, digits) +
      ",\"digits\":" + (string)digits +
      ",\"trade_stops_level\":" + (string)SymbolInfoInteger(detected_symbol, SYMBOL_TRADE_STOPS_LEVEL) +
      ",\"contract_size\":" + DoubleToString(SymbolInfoDouble(detected_symbol, SYMBOL_TRADE_CONTRACT_SIZE), 4) +
      ",\"spread_points\":" + DoubleToString(spread_points, 2) +
      ",\"bars\":" + bars + "}";

   string response;
   if(ApiPost("/market-data", body, response))
   {
      if(!market_history_synced)
      {
         market_sync_step++;
         Print("✅ Broker history sync batch ", market_sync_step, "/5 accepted");
         if(market_sync_step >= 5) market_history_synced = true;
      }
   }
}


//====================================================================
// HEARTBEAT
//====================================================================

void SendHeartbeat()
{
   if(detected_symbol == "")
      return;

   double volume_min =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_VOLUME_MIN
      );

   double volume_max =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_VOLUME_MAX
      );

   double volume_step =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_VOLUME_STEP
      );

   int digits =
      (int)SymbolInfoInteger(
         detected_symbol,
         SYMBOL_DIGITS
      );

   double point =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_POINT
      );

   double ask =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_ASK
      );

   double bid =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_BID
      );

   double spread = 0.0;

   if(point > 0.0)
      spread = (ask - bid) / point;

   bool demo =
      (
         (ENUM_ACCOUNT_TRADE_MODE)
         AccountInfoInteger(
            ACCOUNT_TRADE_MODE
         )
         ==
         ACCOUNT_TRADE_MODE_DEMO
      );

   string body =
      "{"

      "\"account_login\":\"" +
      (string)
      AccountInfoInteger(
         ACCOUNT_LOGIN
      ) +

      "\",\"broker_server\":\"" +
      EscapeJson(
         AccountInfoString(
            ACCOUNT_SERVER
         )
      ) +

      "\",\"is_demo\":" +
      (
         demo
         ? "true"
         : "false"
      ) +

      ",\"resolved_symbol\":\"" +
      EscapeJson(
         detected_symbol
      ) +

      "\",\"asset_family\":\"" +
      EscapeJson(
         detected_asset
      ) +

      "\",\"balance\":" +
      DoubleToString(
         AccountInfoDouble(
            ACCOUNT_BALANCE
         ),
         2
      ) +

      ",\"equity\":" +
      DoubleToString(
         AccountInfoDouble(
            ACCOUNT_EQUITY
         ),
         2
      ) +

      ",\"margin\":" +
      DoubleToString(
         AccountInfoDouble(
            ACCOUNT_MARGIN
         ),
         2
      ) +

      ",\"free_margin\":" +
      DoubleToString(
         AccountInfoDouble(
            ACCOUNT_MARGIN_FREE
         ),
         2
      ) +

      ",\"margin_level\":" +
      DoubleToString(
         AccountInfoDouble(
            ACCOUNT_MARGIN_LEVEL
         ),
         2
      ) +

      ",\"account_currency\":\"" +
      EscapeJson(
         AccountInfoString(
            ACCOUNT_CURRENCY
         )
      ) +

      "\",\"daily_profit\":" +
      DoubleToString(
         DailyProfit(),
         2
      ) +

      ",\"volume_min\":" +
      DoubleToString(
         volume_min,
         4
      ) +

      ",\"volume_max\":" +
      DoubleToString(
         volume_max,
         4
      ) +

      ",\"volume_step\":" +
      DoubleToString(
         volume_step,
         4
      ) +

      ",\"digits\":" +
      (string)digits +

      ",\"spread\":" +
      DoubleToString(
         spread,
         0
      ) +

      ",\"trade_allowed\":" +
      (
         AccountInfoInteger(
            ACCOUNT_TRADE_ALLOWED
         )
         ? "true"
         : "false"
      ) +

      ",\"algo_trading\":" +
      (
         TerminalInfoInteger(
            TERMINAL_TRADE_ALLOWED
         )
         &&
         MQLInfoInteger(
            MQL_TRADE_ALLOWED
         )
         ? "true"
         : "false"
      ) +

      ",\"ea_version\":\"" +
      EscapeJson(
         EaVersion
      ) +

      "\",\"terminal_build\":" +
      (string)
      TerminalInfoInteger(
         TERMINAL_BUILD
      ) +

      ",\"positions\":" +
      PositionJson() +

      "}";

   string response;

   if(ApiPost(
      "/heartbeat",
      body,
      response
   ))
   {
      last_heartbeat =
         TimeCurrent();

      Print(
         "💓 Heartbeat OK: asset=",
         detected_asset,
         " symbol=",
         detected_symbol
      );

      return;
   }

   // One immediate retry. This helps with transient network/backend
   // failures without waiting for the next timer tick.
   Print("⚠️ Heartbeat attempt failed. Retrying once...");

   Sleep(250);

   string retry_response;

   if(ApiPost(
      "/heartbeat",
      body,
      retry_response
   ))
   {
      last_heartbeat =
         TimeCurrent();

      Print(
         "💓 Heartbeat OK on retry: asset=",
         detected_asset,
         " symbol=",
         detected_symbol
      );

      return;
   }

   Print(
      "❌ Heartbeat failed after retry. "
      "The exact HTTP/backend error is shown above."
   );
}


//====================================================================
// CHECK COMMAND SYMBOL / ASSET
//
// Backend can optionally send:
// "symbol":"XAUUSD.p"
// or
// "resolved_symbol":"XAUUSD.p"
// or
// "asset":"XAU"
// or
// "asset_family":"XAU"
//
// If none is provided, command is accepted for the current EA.
//====================================================================

bool CommandBelongsToThisEA(string json)
{
   string command_symbol =
      JsonString(json, "symbol");

   if(command_symbol == "")
      command_symbol =
         JsonString(
            json,
            "resolved_symbol"
         );

   if(command_symbol == "")
      command_symbol =
         JsonString(
            json,
            "broker_symbol"
         );

   // IMPORTANT:
   // The backend uses canonical symbols such as BTCUSD and XAUUSD,
   // while brokers may use BTCUSD.p, BTCUSDm, XAUUSD.p, GOLD, etc.
   // Match by asset FAMILY, never by exact broker symbol.
   //
   // BTCUSD / BTCUSD.p / BTCUSDTm / XBTUSD -> BTC
   // XAUUSD / XAUUSD.p / XAUUSDm / GOLD.p  -> XAU
   if(command_symbol != "")
   {
      string command_family =
         GetAssetFamily(command_symbol);

      if(command_family != "")
      {
         return
            command_family ==
            detected_asset;
      }

      // Unknown symbol: fall through to explicit asset/asset_family
      // if the backend supplied one.
   }

   string command_asset =
      JsonString(json, "asset");

   if(command_asset == "")
      command_asset =
         JsonString(
            json,
            "asset_family"
         );

   if(command_asset != "")
   {
      StringToUpper(command_asset);

      return
         command_asset ==
         detected_asset;
   }

   // Backward compatibility:
   // commands without symbol/asset continue to work.
   return true;
}


//====================================================================
// EXECUTE ENTRY
//====================================================================

string ExecuteEntry(
   string json,
   string &message,
   ulong &ticket
)
{
   if(
      !TerminalInfoInteger(
         TERMINAL_TRADE_ALLOWED
      ) ||
      !MQLInfoInteger(
         MQL_TRADE_ALLOWED
      ) ||
      !AccountInfoInteger(
         ACCOUNT_TRADE_ALLOWED
      )
   )
   {
      message =
         "Trading or Algo Trading is disabled";

      return "rejected";
   }


   // ---------------------------------------------------------------
   // Existing position
   // ---------------------------------------------------------------

   ulong existing;

   if(PositionByMagic(existing))
   {
      ticket = existing;

      message =
         "Entry already executed; idempotent confirmation";

      return "executed";
   }


   // ---------------------------------------------------------------
   // Parse command
   // ---------------------------------------------------------------

   string side =
      JsonString(
         json,
         "direction"
      );

   double lots =
      JsonNumber(
         json,
         "lots"
      );

   double sl_distance =
      JsonNumber(
         json,
         "sl_dist"
      );

   double tp_distance =
      JsonNumber(
         json,
         "tp_dist"
      );


   // ---------------------------------------------------------------
   // Direction
   // ---------------------------------------------------------------

   if(
      side != "BUY" &&
      side != "SELL"
   )
   {
      message =
         "Unsupported entry direction";

      return "rejected";
   }


   // ---------------------------------------------------------------
   // Broker volume rules
   // ---------------------------------------------------------------

   double vmin =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_VOLUME_MIN
      );

   double vmax =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_VOLUME_MAX
      );

   double step =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_VOLUME_STEP
      );

   if(
      lots < vmin ||
      lots > vmax
   )
   {
      message =
         "Lot outside broker min/max";

      return "rejected";
   }


   if(step <= 0.0)
   {
      message =
         "Invalid broker volume step";

      return "rejected";
   }


   double steps =
      (lots - vmin) / step;

   if(
      MathAbs(
         steps -
         MathRound(steps)
      ) > 0.000001
   )
   {
      message =
         "Lot does not match broker step";

      return "rejected";
   }


   // ---------------------------------------------------------------
   // Market price
   // ---------------------------------------------------------------

   ENUM_ORDER_TYPE type =
      side == "BUY"
      ? ORDER_TYPE_BUY
      : ORDER_TYPE_SELL;

   double price =
      side == "BUY"
      ? SymbolInfoDouble(
           detected_symbol,
           SYMBOL_ASK
        )
      : SymbolInfoDouble(
           detected_symbol,
           SYMBOL_BID
        );

   if(price <= 0.0)
   {
      message =
         "Invalid live market price";

      return "rejected";
   }


   // ---------------------------------------------------------------
   // Stops
   // ---------------------------------------------------------------

   int stops =
      (int)
      SymbolInfoInteger(
         detected_symbol,
         SYMBOL_TRADE_STOPS_LEVEL
      );

   double point =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_POINT
      );

   double min_stop_distance =
      stops * point;

   sl_distance =
      MathMax(
         sl_distance,
         min_stop_distance
      );

   tp_distance =
      MathMax(
         tp_distance,
         min_stop_distance
      );


   // ---------------------------------------------------------------
   // SL / TP
   // ---------------------------------------------------------------

   double sl = 0.0;
   double tp = 0.0;

   int digits =
      (int)
      SymbolInfoInteger(
         detected_symbol,
         SYMBOL_DIGITS
      );

   if(side == "BUY")
   {
      sl =
         NormalizeDouble(
            price - sl_distance,
            digits
         );

      tp =
         NormalizeDouble(
            price + tp_distance,
            digits
         );
   }
   else
   {
      sl =
         NormalizeDouble(
            price + sl_distance,
            digits
         );

      tp =
         NormalizeDouble(
            price - tp_distance,
            digits
         );
   }


   if(sl <= 0.0 || tp <= 0.0)
   {
      message =
         "Invalid SL/TP";

      return "rejected";
   }


   // ---------------------------------------------------------------
   // Margin
   // ---------------------------------------------------------------

   double margin = 0.0;

   if(
      !OrderCalcMargin(
         type,
         detected_symbol,
         lots,
         price,
         margin
      )
   )
   {
      message =
         "Unable to calculate margin";

      return "rejected";
   }

   if(
      margin >
      AccountInfoDouble(
         ACCOUNT_MARGIN_FREE
      )
   )
   {
      message =
         "Insufficient free margin";

      return "rejected";
   }


   // ---------------------------------------------------------------
   // Trade configuration
   // ---------------------------------------------------------------

   trade.SetExpertMagicNumber(
      MagicNumber
   );

   trade.SetDeviationInPoints(
      MaxDeviationPoints
   );

   trade.SetTypeFillingBySymbol(
      detected_symbol
   );


   // ---------------------------------------------------------------
   // Execute
   // ---------------------------------------------------------------

   string comment =
      detected_asset == "BTC"
      ? "BTC Universal Bridge"
      : "XAU Universal Bridge";

   bool ok;

   if(side == "BUY")
   {
      ok =
         trade.Buy(
            lots,
            detected_symbol,
            price,
            sl,
            tp,
            comment
         );
   }
   else
   {
      ok =
         trade.Sell(
            lots,
            detected_symbol,
            price,
            sl,
            tp,
            comment
         );
   }


   message =
      trade.ResultRetcodeDescription();


   if(
      !ok ||
      !TradeRequestAccepted()
   )
   {
      return "failed";
   }


   Sleep(200);


   if(
      PositionByMagic(ticket) &&
      PositionSelectByTicket(ticket)
   )
   {
      SaveManagementState(json, ticket, sl_distance);
      return "executed";
   }


   return "accepted";
}


//====================================================================
// SEND ACK
//====================================================================

void SendAck(
   string command_id,
   string outcome,
   ulong ticket,
   string message
)
{
   double price = 0.0;
   double volume = 0.0;

   if(
      ticket > 0 &&
      PositionSelectByTicket(ticket)
   )
   {
      price =
         PositionGetDouble(
            POSITION_PRICE_OPEN
         );

      volume =
         PositionGetDouble(
            POSITION_VOLUME
         );
   }


   bool success =
      outcome == "executed" ||
      outcome == "accepted";


   string body =
      "{"

      "\"command_id\":\"" +
      EscapeJson(
         command_id
      ) +

      "\",\"success\":" +
      (
         success
         ? "true"
         : "false"
      ) +

      ",\"result\":\"" +
      EscapeJson(
         outcome
      ) +

      "\",\"asset\":\"" +
      EscapeJson(
         detected_asset
      ) +

      "\",\"resolved_symbol\":\"" +
      EscapeJson(
         detected_symbol
      ) +

      "\",\"broker_ticket\":" +
      (
         ticket > 0
         ? "\"" +
           (string)ticket +
           "\""
         : "null"
      ) +

      ",\"broker_deal\":" +
      (
         trade.ResultDeal() > 0
         ? "\"" +
           (string)
           trade.ResultDeal() +
           "\""
         : "null"
      ) +

      ",\"broker_retcode\":" +
      (string)
      trade.ResultRetcode() +

      ",\"broker_message\":\"" +
      EscapeJson(
         message
      ) +

      "\",\"filled_price\":" +
      DoubleToString(
         price,
         8
      ) +

      ",\"filled_volume\":" +
      DoubleToString(
         volume,
         4
      ) +

      "}";


   string response;

   ApiPost(
      "/ack",
      body,
      response
   );
}



//====================================================================
// PARSE BACKEND SERVER TIME
//====================================================================
// Converts the backend's UTC ISO-8601 server_time into Unix epoch
// seconds without using the VPS/terminal timezone or local clock.
//
// Expected format:
//   2026-09-01T04:20:00+00:00
//   2026-09-01T04:20:00Z
//====================================================================

long DaysFromCivil(
   int year,
   int month,
   int day
)
{
   year -= (month <= 2 ? 1 : 0);

   long era =
      (year >= 0
       ? year
       : year - 399) / 400;

   long yoe =
      year - era * 400;

   long mp =
      month + (month > 2 ? -3 : 9);

   long doy =
      (153 * mp + 2) / 5 + day - 1;

   long doe =
      yoe * 365 +
      yoe / 4 -
      yoe / 100 +
      doy;

   return
      era * 146097 +
      doe -
      719468;
}


long ParseBackendServerTime(string value)
{
   if(StringLen(value) < 19)
      return 0;

   // YYYY-MM-DDTHH:MM:SS
   int year =
      (int)StringToInteger(
         StringSubstr(value, 0, 4)
      );

   int month =
      (int)StringToInteger(
         StringSubstr(value, 5, 2)
      );

   int day =
      (int)StringToInteger(
         StringSubstr(value, 8, 2)
      );

   int hour =
      (int)StringToInteger(
         StringSubstr(value, 11, 2)
      );

   int minute =
      (int)StringToInteger(
         StringSubstr(value, 14, 2)
      );

   int second =
      (int)StringToInteger(
         StringSubstr(value, 17, 2)
      );

   if(
      year < 1970 ||
      month < 1 ||
      month > 12 ||
      day < 1 ||
      day > 31 ||
      hour < 0 ||
      hour > 23 ||
      minute < 0 ||
      minute > 59 ||
      second < 0 ||
      second > 59
   )
   {
      return 0;
   }

   return
      DaysFromCivil(
         year,
         month,
         day
      ) * 86400L +
      (long)hour * 3600L +
      (long)minute * 60L +
      (long)second;
}


//====================================================================
// ESTIMATED BACKEND CURRENT TIME
//====================================================================
// The backend server_time is the authoritative clock baseline.
// GetTickCount64() is used only to measure elapsed time since the
// response was received, so VPS clock changes cannot affect expiry.
//
// Returns Unix epoch seconds.
//====================================================================

long EstimatedBackendNow(
   long backend_server_epoch,
   ulong response_received_ms
)
{
   if(backend_server_epoch <= 0)
      return 0;

   ulong now_ms =
      GetTickCount64();

   ulong elapsed_ms = 0;

   if(now_ms >= response_received_ms)
      elapsed_ms =
         now_ms - response_received_ms;

   return
      backend_server_epoch +
      (long)(elapsed_ms / 1000);
}

//====================================================================
// POLL COMMAND
//====================================================================

void PollCommand()
{
   string response;

   if(
      !ApiPost(
         "/poll",
         "{}",
         response
      )
   )
   {
      return;
   }

   // IMPORTANT:
   // Do not use TimeGMT()/TimeLocal()/TimeCurrent() to validate
   // command expiry. The backend server_time is the authoritative
   // clock baseline, and GetTickCount64() only measures elapsed
   // time since this response was received.
   string backend_server_time =
      JsonString(
         response,
         "server_time"
      );

   long backend_server_epoch =
      ParseBackendServerTime(
         backend_server_time
      );

   ulong response_received_ms =
      GetTickCount64();


   string command_id =
      JsonString(
         response,
         "id"
      );

   string action =
      JsonString(
         response,
         "action"
      );


   if(
      command_id == "" ||
      action == ""
   )
   {
      return;
   }


   // ---------------------------------------------------------------
   // Make sure command belongs to this EA/symbol
   // ---------------------------------------------------------------

   if(!CommandBelongsToThisEA(response))
   {
      Print(
         "ℹ️ Command ",
         command_id,
         " is for another asset family. Rejecting."
      );

      // ACK it so the backend does not keep dispatching the same
      // incompatible command forever.
      SendAck(
         command_id,
         "rejected",
         0,
         "Command is for another asset family"
      );

      return;
   }


   // ---------------------------------------------------------------
   // Expiry
   // ---------------------------------------------------------------
   // The backend server_time is authoritative.
   //
   // NEVER compare expires_epoch against TimeGMT(), TimeLocal(),
   // TimeCurrent(), or any other VPS/terminal clock here.
   //
   // We establish a backend-time baseline from server_time and then
   // advance it using GetTickCount64(), which is independent of the
   // VPS wall-clock setting.
   // ---------------------------------------------------------------

   long expires_epoch =
      (long)
      JsonNumber(
         response,
         "expires_epoch",
         0
      );

   if(expires_epoch > 0)
   {
      if(backend_server_epoch <= 0)
      {
         Print(
            "❌ Cannot validate command expiry: backend server_time "
            "is missing or invalid."
         );

         SendAck(
            command_id,
            "rejected",
            0,
            "Command expiry could not be validated: invalid backend server_time"
         );

         return;
      }

      long estimated_backend_now =
         EstimatedBackendNow(
            backend_server_epoch,
            response_received_ms
         );

      if(
         estimated_backend_now > 0 &&
         estimated_backend_now >= expires_epoch
      )
      {
         SendAck(
            command_id,
            "rejected",
            0,
            "Entry command expired according to backend server time"
         );

         return;
      }
   }


   string outcome =
      "rejected";

   string message =
      "Unsupported command";

   ulong ticket = 0;


   // ---------------------------------------------------------------
   // ENTRY
   // ---------------------------------------------------------------

   if(action == "ENTRY")
   {
      if(
         CommandWasExecuted(
            command_id
         )
      )
      {
         PositionByMagic(ticket);

         outcome =
            "executed";

         message =
            "Command already executed; restored from local journal";
      }
      else
      {
         outcome =
            ExecuteEntry(
               response,
               message,
               ticket
            );
      }
   }


   // ---------------------------------------------------------------
   // CLOSE
   // ---------------------------------------------------------------

   else if(action == "CLOSE")
   {
      ticket =
         (ulong)
         StringToInteger(
            JsonString(
               response,
               "ticket"
            )
         );

      if(ticket == 0)
      {
         ticket =
            (ulong)
            JsonNumber(
               response,
               "ticket",
               0
            );
      }


      if(
         ticket == 0 ||
         !PositionSelectByTicket(ticket)
      )
      {
         outcome =
            "executed";

         message =
            "Position already closed; idempotent confirmation";
      }
      else
      {
         // ----------------------------------------------------------
         // Safety: close only position belonging to this EA
         // and current detected symbol.
         // ----------------------------------------------------------

         string position_symbol =
            PositionGetString(
               POSITION_SYMBOL
            );

         ulong position_magic =
            (ulong)
            PositionGetInteger(
               POSITION_MAGIC
            );


         if(
            position_symbol != detected_symbol ||
            position_magic != MagicNumber
         )
         {
            outcome =
               "rejected";

            message =
               "Position does not belong to this EA/symbol";
         }
         else
         {
            bool requested =
               trade.PositionClose(
                  ticket
               );

            message =
               trade.ResultRetcodeDescription();

            if(
               !requested ||
               !TradeRequestAccepted()
            )
            {
               outcome =
                  "failed";
            }
            else
            {
               Sleep(200);

               outcome =
                  PositionSelectByTicket(ticket)
                  ? "accepted"
                  : "executed";
            }
         }
      }
   }


   // ---------------------------------------------------------------
   // Remember successful command
   // ---------------------------------------------------------------

   if(outcome == "executed")
   {
      RememberExecutedCommand(
         command_id
      );
   }


   // ---------------------------------------------------------------
   // ACK
   // ---------------------------------------------------------------

   SendAck(
      command_id,
      outcome,
      ticket,
      message
   );
}


//====================================================================
// INITIALIZE
//====================================================================

int OnInit()
{
   init_attempts++;


   Print("========================================");
   Print(
      "🚀 Universal Asset Bridge v",
      EaVersion,
      " initializing..."
   );
   Print(
      "   Attempt #",
      init_attempts
   );
   Print(
      "   Time: ",
      TimeToString(
         TimeCurrent()
      )
   );
   Print(
      "   Account: ",
      AccountInfoInteger(
         ACCOUNT_LOGIN
      )
   );
   Print(
      "   Server: ",
      AccountInfoString(
         ACCOUNT_SERVER
      )
   );
   Print(
      "   Chart Symbol: ",
      _Symbol
   );
   Print("========================================");


   // ---------------------------------------------------------------
   // Algo Trading
   // ---------------------------------------------------------------

   if(
      !TerminalInfoInteger(
         TERMINAL_TRADE_ALLOWED
      ) ||
      !MQLInfoInteger(
         MQL_TRADE_ALLOWED
      )
   )
   {
      Print("❌ Algo Trading is disabled!");
      Print(
         "   Enable Algo Trading in MT5."
      );

      return INIT_FAILED;
   }


   // ---------------------------------------------------------------
   // WebRequest
   // ---------------------------------------------------------------

   webrequest_ready = true;

   Print(
      "🔍 Testing WebRequest to: ",
      BridgeUrl
   );

   string test_response;

   if(
      !ApiPost(
         "/ping",
         "{}",
         test_response
      )
   )
   {
      Print(
         "⚠️ WebRequest test failed."
      );

      Print(
         "   Tools → Options → Expert Advisors"
      );

      Print(
         "   Add URL: ",
         BridgeUrl
      );

      // Do not permanently disable WebRequest after a failed ping.
      // Heartbeat and poll will retry on the next timer cycle.
      webrequest_ready = true;

      // Don't fail EA; the connection can recover on its own.
   }
   else
   {
      Print(
         "✅ WebRequest test passed!"
      );
   }


   // ---------------------------------------------------------------
   // Token
   // ---------------------------------------------------------------

   if(
      BridgeToken == "" ||
      BridgeToken == "PASTE_YOUR_TOKEN"
   )
   {
      Print(
         "❌ Bridge token is not configured."
      );

      return INIT_PARAMETERS_INCORRECT;
   }


   // ---------------------------------------------------------------
   // Detect symbol
   // ---------------------------------------------------------------

   Print(
      "🔍 Detecting BTC/XAU symbol..."
   );

   detected_symbol =
      DetectUniversalSymbol();


   if(detected_symbol == "")
   {
      Print(
         "❌ No supported BTC/XAU symbol found."
      );

      Print(
         "   BTC examples: BTCUSD, BTCUSD.p, BTCUSDT..."
      );

      Print(
         "   XAU examples: XAUUSD, XAUUSD.p, GOLD..."
      );

      return INIT_FAILED;
   }


   detected_asset =
      GetAssetFamily(
         detected_symbol
      );


   // ---------------------------------------------------------------
   // Symbol information
   // ---------------------------------------------------------------

   double point =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_POINT
      );

   double ask =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_ASK
      );

   double bid =
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_BID
      );

   double spread = 0.0;

   if(point > 0.0)
      spread =
         (ask - bid) /
         point;


   Print("========================================");

   Print(
      "✅ UNIVERSAL SYMBOL DETECTED"
   );

   Print(
      "   Asset: ",
      detected_asset
   );

   Print(
      "   Symbol: ",
      detected_symbol
   );

   Print(
      "   Digits: ",
      SymbolInfoInteger(
         detected_symbol,
         SYMBOL_DIGITS
      )
   );

   Print(
      "   Spread: ",
      spread
   );

   Print(
      "   Min Volume: ",
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_VOLUME_MIN
      )
   );

   Print(
      "   Max Volume: ",
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_VOLUME_MAX
      )
   );

   Print(
      "   Volume Step: ",
      SymbolInfoDouble(
         detected_symbol,
         SYMBOL_VOLUME_STEP
      )
   );

   Print("========================================");


   // ---------------------------------------------------------------
   // Account-specific globals
   // ---------------------------------------------------------------

   gv_prefix +=
      (string)
      AccountInfoInteger(
         ACCOUNT_LOGIN
      ) +
      "_" +
      (string)
      MagicNumber +
      "_" +
      detected_symbol +
      "_";


   // ---------------------------------------------------------------
   // IMPORTANT:
   // Journal is now symbol-specific.
   // This prevents BTC/XAU instances from sharing command history.
   // ---------------------------------------------------------------

   journal_file =
      "GPT_MT5_" +
      (string)
      AccountInfoInteger(
         ACCOUNT_LOGIN
      ) +
      "_" +
      (string)
      MagicNumber +
      "_" +
      detected_symbol +
      ".journal";


   // ---------------------------------------------------------------
   // Trade setup
   // ---------------------------------------------------------------

   trade.SetExpertMagicNumber(
      MagicNumber
   );

   trade.SetDeviationInPoints(
      MaxDeviationPoints
   );

   trade.SetTypeFillingBySymbol(
      detected_symbol
   );


   // ---------------------------------------------------------------
   // Timer
   // ---------------------------------------------------------------

   EventSetTimer(
      MathMax(
         1,
         PollSeconds
      )
   );


   // ---------------------------------------------------------------
   // Initial heartbeat
   // ---------------------------------------------------------------

   Print(
      "📤 Sending initial heartbeat..."
   );

   SendHeartbeat();


   Print("========================================");

   Print(
      "✅ UNIVERSAL EA INITIALIZED"
   );

   Print(
      "   Asset: ",
      detected_asset
   );

   Print(
      "   Symbol: ",
      detected_symbol
   );

   Print(
      "   Magic: ",
      MagicNumber
   );

   Print(
      "   Poll: ",
      PollSeconds,
      "s"
   );

   Print("========================================");


   return INIT_SUCCEEDED;
}


//====================================================================
// DEINITIALIZE
//====================================================================

void OnDeinit(
   const int reason
)
{
   EventKillTimer();

   Print("========================================");

   Print(
      "🛑 Universal EA stopped."
   );

   Print(
      "   Reason: ",
      reason
   );

   Print(
      "   Asset: ",
      detected_asset
   );

   Print(
      "   Symbol: ",
      detected_symbol
   );

   Print(
      "   Time: ",
      TimeToString(
         TimeCurrent()
      )
   );

   Print("========================================");
}


//====================================================================
// TIMER
//====================================================================

void OnTimer()
{
   // ---------------------------------------------------------------
   // Re-detect if symbol is lost
   // ---------------------------------------------------------------

   if(detected_symbol == "")
   {
      detected_symbol =
         DetectUniversalSymbol();

      if(detected_symbol == "")
         return;

      detected_asset =
         GetAssetFamily(
            detected_symbol
         );
   }


   // ---------------------------------------------------------------
   // Broker ticks and closed candles
   // ---------------------------------------------------------------

   SendMarketData();


   // ---------------------------------------------------------------
   // Heartbeat
   // ---------------------------------------------------------------

   SendHeartbeat();


   // ---------------------------------------------------------------
   // Poll commands
   // ---------------------------------------------------------------

   PollCommand();
}


//====================================================================
// TICK
//====================================================================

void OnTick()
{
   ManageOpenPosition();
}


//+------------------------------------------------------------------+
//| END OF UNIVERSAL BTC/XAU BRIDGE                                  |
//+------------------------------------------------------------------+