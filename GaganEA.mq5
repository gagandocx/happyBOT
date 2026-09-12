//+------------------------------------------------------------------+
//|                                        GaganEA v2.10 |
//|                           Reconstructed from UI + Backtest Data  |
//|                                                                  |
//| KEY FINDINGS FROM BACKTEST ANALYSIS:                             |
//|  - $1000 -> $8970 in 28 days (797% growth)                      |
//|  - 1246 trade events, consistent ~8.5% deposit load per trade    |
//|  - Each trade cycle: open -> T1 partial -> T2 partial -> T3/SL   |
//|  - 872 "FLAT" periods (no positions) = EA waits for clean signal |
//|  - 12 big SL hits (~$100-750 range) = basket SL events           |
//|  - 276 multi-close events = basket/partial close sequences       |
//|  - Deposit load always ~8.7% = risk-based lot sizing working     |
//|  - Tiny -$0.11 recurring losses = swap/commission on partials    |
//+------------------------------------------------------------------+
#property copyright "GaganEA v2.10"
#property version   "2.10"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        trade;
CPositionInfo posInfo;

//+------------------------------------------------------------------+
//| Enumerations                                                      |
//+------------------------------------------------------------------+
enum ENUM_MASTER_MODE
{
   MODE_LAST_2           = 1,
   MODE_LAST_3           = 2,
   MODE_FIRST_2_LAST_1   = 3,
   MODE_FIRST_MID_LAST   = 4,
   MODE_SEC_MID_LAST     = 5,
   MODE_ALL_SIMULTANEOUS = 6
};

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+

input group "=== TREND CHECK (HTF) ==="
input ENUM_TIMEFRAMES HTF_Timeframe       = PERIOD_H1;
input int             EMA_Period_HTF      = 200;

input group "=== TRADE EXECUTION (Current TF) ==="
input ENUM_TIMEFRAMES Trade_Timeframe     = PERIOD_M5;
input int             EMA_Period_CTF      = 200;
input int             Min_EMA_Distance    = 150;

input group "=== LOT SIZE ==="
input double          Manual_LotSize      = 0.0;
input double          Risk_Percent        = 6.0;
input double          Max_LotSize         = 10.0;

input group "=== STOP LOSS & TARGETS ==="
input bool            Use_StopLoss        = true;
input int             StopLoss_Pips       = 2500;
input int             T1_Pips             = 800;
input int             T2_Pips             = 1200;
input int             T3_Pips             = 2000;
input double          T1_ClosePercent     = 65.0;
input double          T2_ClosePercent     = 80.0;
input double          T3_ClosePercent     = 100.0;

input group "=== TRAILING STOP (Individual) ==="
input int             Trail_Step_Pips     = 30;

input group "=== AMA TREND-FLIP EXIT (M1) ==="
input bool             Use_AMA_Exit        = true;
input int              AMA_Period          = 21;
input int              AMA_Fast_EMA        = 2;
input int              AMA_Slow_EMA        = 30;
input int              AMA_Shift           = 0;
input int              AMA_Confirm_Candles = 3;

input group "=== REVERSAL DETECTION EXIT ==="
input bool            Use_Reversal_Exit           = true;
input int             Reversal_Min_Confirmations  = 2;
input int             RSI_Period                  = 14;
input double          RSI_OB_Level                = 70.0;
input double          RSI_OS_Level                = 30.0;
input int             MACD_Fast                   = 12;
input int             MACD_Slow                   = 26;
input int             MACD_Signal                 = 9;
input int             ADX_Period                  = 14;
input double          ADX_Trend_Threshold         = 25.0;
input double          ADX_Weak_Threshold          = 20.0;
input double          Volume_Spike_Multiplier     = 1.5;
input int             Volume_Average_Periods      = 20;
input ENUM_TIMEFRAMES Reversal_Timeframe          = PERIOD_M5;

input group "=== AVERAGING BASKET TRAILING (Same-Side) ==="
input bool            Use_Basket_Trailing = true;
input double          Basket_Lock_Pips    = 30.0;
input double          Basket_Trail_Step   = 15.0;

input group "=== MULTI-TRADE SETTINGS ==="
input int             Min_Trade_Distance  = 20;
input int             Max_Trade_Distance  = 40;

input group "=== EQUITY PROTECTION (Global Close) ==="
input bool            Use_EP_Percent      = true;
input double          EP_Max_DD_Percent   = 5.5;
input bool            Use_EP_Money        = false;
input double          EP_Max_DD_Money     = 200.0;

input group "=== MASTER EQUITY PROTECTION ==="
input bool            Use_Master_EP                = true;
input double          Master_Trigger_DD_Percent    = 1.5;
input int             Master_Trigger_Min_Trades    = 3;
input ENUM_MASTER_MODE Master_Logic_Mode           = MODE_ALL_SIMULTANEOUS;
input double          Master_Lock_Pips             = 30.0;
input double          Master_Trail_Step            = 15.0;

input group "=== HIGH IMPACT NEWS FILTER ==="
input bool            News_Filter_Enable  = false;
input int             News_Pause_Before   = 30;
input int             News_Pause_After    = 30;

input group "=== CANDLESTICK PATTERNS ==="
input bool            Use_Hammer         = true;
input bool            Use_InvHammer      = true;
input bool            Use_BullEngulf     = true;
input bool            Use_PiercingLine   = true;
input bool            Use_MorningStar    = true;
input bool            Use_ThreeWhite     = true;
input bool            Use_BullHarami     = true;
input bool            Use_Doji           = true;
input bool            Use_ShootingStar   = true;
input bool            Use_BearEngulf     = true;
input bool            Use_EveningStar    = true;
input bool            Use_ThreeBlack     = true;
input bool            Use_DarkCloud      = true;
input bool            Use_BearHarami     = true;
input bool            Use_HangingMan     = true;

input group "=== CHART PATTERNS ==="
input bool            Use_DoubleTop      = true;
input bool            Use_DoubleBottom   = true;
input bool            Use_HeadShoulders  = true;
input bool            Use_InvHeadShould  = true;
input bool            Use_BearFlag       = true;
input bool            Use_BullFlag       = true;
input bool            Use_RisingWedge    = true;
input bool            Use_FallingWedge   = true;
input bool            Use_BearTriangle   = true;
input bool            Use_BullTriangle   = true;

input group "=== NEWS FILTER ==="
input bool            News_FilterEnable  = false;

input group "=== DASHBOARD & MAGIC ==="
input bool            Show_Dashboard     = true;
input int             Dashboard_X        = 15;
input int             Dashboard_Y        = 30;
input int             Magic_Number       = 202400;
input int             Max_Slippage       = 10;
input int             Max_Spread_Pips    = 50;
input string          EA_Comment         = "GaganEA";

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                  |
//+------------------------------------------------------------------+
int ema_htf_handle, ema_ctf_handle, ama_handle;
int rsi_handle, macd_handle, adx_handle, vol_handle;
int reversal_buy_signals, reversal_sell_signals;

string lbl = "GEA_";
int open_buy_count, open_sell_count;
double buyAvgPrice, sellAvgPrice;
double buyTotalLots, sellTotalLots;
double buyProfitPips, sellProfitPips;
double floating_pnl;
double basketBuyHigh, basketSellHigh;
double basketBuyTrail, basketSellTrail;
bool   basketBuyActive, basketSellActive;

// Master EP
double masterBuyHigh, masterSellHigh;
double masterBuyTrail, masterSellTrail;
bool   masterBuyActive, masterSellActive;

// AMA exit
double prevAMA;
int    amaFlipBuy, amaFlipSell;
string amaStatus;

// Targets tracking
ulong  t1_tickets[];
ulong  t2_tickets[];

// PnL cache
datetime pnl_cache_time;
double pnl_today, pnl_yesterday, pnl_week, pnl_month, pnl_last_month;

// Trend state
bool   htf_bullish, htf_bearish;
bool   ctf_above_ema, ctf_below_ema;
double ema_distance_pips;
string current_signal;
color  signal_color;
double pip, point_size;

// News and time
bool     news_active;
datetime last_bar_time;
datetime last_m1_bar_time;

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(Magic_Number);
   trade.SetDeviationInPoints(Max_Slippage);
   
   ema_htf_handle = iMA(_Symbol, HTF_Timeframe, EMA_Period_HTF, 0, MODE_EMA, PRICE_CLOSE);
   ema_ctf_handle = iMA(_Symbol, Trade_Timeframe, EMA_Period_CTF, 0, MODE_EMA, PRICE_CLOSE);
   
   if(ema_htf_handle == INVALID_HANDLE || ema_ctf_handle == INVALID_HANDLE)
   {
      Print("Failed to create EMA handles");
      return INIT_FAILED;
   }
   
   if(Use_AMA_Exit)
   {
      ama_handle = iAMA(_Symbol, PERIOD_M1, AMA_Period, AMA_Fast_EMA, AMA_Slow_EMA, AMA_Shift, PRICE_CLOSE);
      if(ama_handle == INVALID_HANDLE)
      {
         Print("Failed to create AMA handle");
         return INIT_FAILED;
      }
   }
   
   if(Use_Reversal_Exit)
   {
      rsi_handle  = iRSI(_Symbol, Reversal_Timeframe, RSI_Period, PRICE_CLOSE);
      macd_handle = iMACD(_Symbol, Reversal_Timeframe, MACD_Fast, MACD_Slow, MACD_Signal, PRICE_CLOSE);
      adx_handle  = iADX(_Symbol, Reversal_Timeframe, ADX_Period);
      vol_handle  = iVolumes(_Symbol, Reversal_Timeframe, VOLUME_TICK);
      
      if(rsi_handle == INVALID_HANDLE || macd_handle == INVALID_HANDLE ||
         adx_handle == INVALID_HANDLE || vol_handle == INVALID_HANDLE)
      {
         Print("Failed to create Reversal Detection handles");
         return INIT_FAILED;
      }
   }
   
   ArrayResize(t1_tickets, 0);
   ArrayResize(t2_tickets, 0);
   prevAMA = 0;
   amaFlipBuy = 0;
   amaFlipSell = 0;
   amaStatus = "---";
   reversal_buy_signals = 0;
   reversal_sell_signals = 0;
   
   // Initialize pip/point
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   point_size = _Point;
   pip = (digits == 3 || digits == 5) ? point_size * 10 : point_size;
   
   // Initialize state
   htf_bullish = false;
   htf_bearish = false;
   ctf_above_ema = false;
   ctf_below_ema = false;
   ema_distance_pips = 0;
   current_signal = "---";
   signal_color = clrGray;
   floating_pnl = 0;
   news_active = false;
   last_bar_time = 0;
   last_m1_bar_time = 0;
   pnl_last_month = 0;
   
   if(Show_Dashboard) CreateDashboard();
   
   Print("GaganEA v2.10 initialized on ", _Symbol, " TF:", EnumToString(Trade_Timeframe));
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(ema_htf_handle != INVALID_HANDLE) IndicatorRelease(ema_htf_handle);
   if(ema_ctf_handle != INVALID_HANDLE) IndicatorRelease(ema_ctf_handle);
   if(Use_AMA_Exit && ama_handle != INVALID_HANDLE) IndicatorRelease(ama_handle);
   
   if(Use_Reversal_Exit)
   {
      if(rsi_handle != INVALID_HANDLE)  IndicatorRelease(rsi_handle);
      if(macd_handle != INVALID_HANDLE) IndicatorRelease(macd_handle);
      if(adx_handle != INVALID_HANDLE)  IndicatorRelease(adx_handle);
      if(vol_handle != INVALID_HANDLE)  IndicatorRelease(vol_handle);
   }
   
   DeleteDashboard();
   Print("GaganEA v2.10 removed. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   // Refresh position data
   CountOpenPositions();
   
   // Compute floating P/L
   floating_pnl = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      floating_pnl += posInfo.Profit() + posInfo.Swap() + posInfo.Commission();
   }
   
   // Update trend state for dashboard
   double emaHTF_tick[], emaCTF_tick[];
   ArraySetAsSeries(emaHTF_tick, true);
   ArraySetAsSeries(emaCTF_tick, true);
   if(CopyBuffer(ema_htf_handle, 0, 0, 1, emaHTF_tick) >= 1)
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      htf_bullish = (bid > emaHTF_tick[0]);
      htf_bearish = (bid < emaHTF_tick[0]);
   }
   if(CopyBuffer(ema_ctf_handle, 0, 0, 1, emaCTF_tick) >= 1)
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      ctf_above_ema = (bid > emaCTF_tick[0]);
      ctf_below_ema = (bid < emaCTF_tick[0]);
      ema_distance_pips = MathAbs(bid - emaCTF_tick[0]) / pip;
   }
   
   // Update signal state
   int bp = DetectBullishPattern();
   int sp = DetectBearishPattern();
   if(bp > 0) { current_signal = "BUY #" + IntegerToString(bp); signal_color = clrLime; }
   else if(sp > 0) { current_signal = "SELL #" + IntegerToString(sp); signal_color = clrTomato; }
   else { current_signal = "Scanning..."; signal_color = clrGray; }
   
   // News state
   news_active = ((News_Filter_Enable || News_FilterEnable) && IsNewsTime());
   
   // Equity Protection
   if(CheckEquityProtection()) return;
   
   // Master Equity Protection
   if(Use_Master_EP)
      CheckMasterEquityProtection();
   
   // Manage open trades
   ManageTargets();
   ManageIndividualTrailing();
   
   // AMA Exit
   if(Use_AMA_Exit)
      ManageAMAExit();
   
   // Reversal Detection Exit
   if(Use_Reversal_Exit)
      ManageReversalExit();
   
   // Basket trailing
   if(Use_Basket_Trailing)
      ManageBasketTrailing();
   
   // New bar check for entries
   static datetime lastBar = 0;
   datetime curBar = iTime(_Symbol, Trade_Timeframe, 0);
   if(curBar == lastBar) { if(Show_Dashboard) UpdateDashboard(); return; }
   lastBar = curBar;
   last_bar_time = curBar;
   
   // Spread filter
   if(Max_Spread_Pips > 0)
   {
      long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
      if(spread > Max_Spread_Pips) { if(Show_Dashboard) UpdateDashboard(); return; }
   }
   
   // News filter
   if(news_active)
   { if(Show_Dashboard) UpdateDashboard(); return; }
   
   // Entry logic
   OpenTrade();
   
   if(Show_Dashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
//| Open Trade Logic                                                  |
//+------------------------------------------------------------------+
void OpenTrade()
{
   double emaHTF[], emaCTF[];
   ArraySetAsSeries(emaHTF, true);
   ArraySetAsSeries(emaCTF, true);
   if(CopyBuffer(ema_htf_handle, 0, 0, 3, emaHTF) < 3) return;
   if(CopyBuffer(ema_ctf_handle, 0, 0, 3, emaCTF) < 3) return;
   
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   
   bool htfBull = (bid > emaHTF[0]);
   bool htfBear = (bid < emaHTF[0]);
   bool ctfBull = (bid > emaCTF[0]);
   bool ctfBear = (bid < emaCTF[0]);
   double dist  = MathAbs(bid - emaCTF[0]) / _Point;
   bool farEnough = (dist >= Min_EMA_Distance);
   
   // BUY
   if(htfBull && ctfBull && farEnough)
   {
      int pat = DetectBullishPattern();
      if(pat > 0 && DistanceCheckOK(ORDER_TYPE_BUY))
      {
         double lots = CalcLotSize();
         double sl = Use_StopLoss ? (ask - StopLoss_Pips * _Point) : 0;
         if(trade.Buy(lots, _Symbol, ask, sl, 0, EA_Comment))
            Print("BUY opened: ", DoubleToString(lots,2), " lots | Pattern:", pat);
      }
   }
   
   // SELL
   if(htfBear && ctfBear && farEnough)
   {
      int pat = DetectBearishPattern();
      if(pat > 0 && DistanceCheckOK(ORDER_TYPE_SELL))
      {
         double lots = CalcLotSize();
         double sl = Use_StopLoss ? (bid + StopLoss_Pips * _Point) : 0;
         if(trade.Sell(lots, _Symbol, bid, sl, 0, EA_Comment))
            Print("SELL opened: ", DoubleToString(lots,2), " lots | Pattern:", pat);
      }
   }
}

//+------------------------------------------------------------------+
//| Calculate Lot Size                                                |
//+------------------------------------------------------------------+
double CalcLotSize()
{
   if(Manual_LotSize > 0) return NormalizeLot(Manual_LotSize);
   
   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmt  = balance * Risk_Percent / 100.0;
   double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSize <= 0) return SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   
   double slDist = StopLoss_Pips * _Point;
   double lots = riskAmt / ((slDist / tickSize) * tickVal);
   return NormalizeLot(lots);
}

//+------------------------------------------------------------------+
//| Normalize Lot                                                     |
//+------------------------------------------------------------------+
double NormalizeLot(double lots)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lots = MathFloor(lots / step) * step;
   lots = MathMax(lots, minLot);
   lots = MathMin(lots, MathMin(maxLot, Max_LotSize));
   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
//| Count Open Positions                                              |
//+------------------------------------------------------------------+
void CountOpenPositions()
{
   open_buy_count = 0; open_sell_count = 0;
   buyAvgPrice = 0; sellAvgPrice = 0;
   buyTotalLots = 0; sellTotalLots = 0;
   buyProfitPips = 0; sellProfitPips = 0;
   
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      
      double op = posInfo.PriceOpen();
      double lt = posInfo.Volume();
      
      if(posInfo.PositionType() == POSITION_TYPE_BUY)
      {
         open_buy_count++;
         buyAvgPrice += op * lt;
         buyTotalLots += lt;
         buyProfitPips += (SymbolInfoDouble(_Symbol, SYMBOL_BID) - op) / _Point;
      }
      else
      {
         open_sell_count++;
         sellAvgPrice += op * lt;
         sellTotalLots += lt;
         sellProfitPips += (op - SymbolInfoDouble(_Symbol, SYMBOL_ASK)) / _Point;
      }
   }
   if(buyTotalLots > 0)  buyAvgPrice /= buyTotalLots;
   if(sellTotalLots > 0) sellAvgPrice /= sellTotalLots;
}

//+------------------------------------------------------------------+
//| Distance Check                                                    |
//+------------------------------------------------------------------+
bool DistanceCheckOK(ENUM_ORDER_TYPE type)
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      
      if(type == ORDER_TYPE_BUY && posInfo.PositionType() == POSITION_TYPE_BUY)
      {
         if(MathAbs(bid - posInfo.PriceOpen()) / _Point < Min_Trade_Distance)
            return false;
      }
      if(type == ORDER_TYPE_SELL && posInfo.PositionType() == POSITION_TYPE_SELL)
      {
         if(MathAbs(bid - posInfo.PriceOpen()) / _Point < Min_Trade_Distance)
            return false;
      }
   }
   return true;
}

//+------------------------------------------------------------------+
//| Manage Targets (T1, T2, T3)                                      |
//+------------------------------------------------------------------+
void ManageTargets()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      
      ulong ticket = posInfo.Ticket();
      double op = posInfo.PriceOpen();
      double lots = posInfo.Volume();
      double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      
      double pips = 0;
      if(posInfo.PositionType() == POSITION_TYPE_BUY)
         pips = (SymbolInfoDouble(_Symbol, SYMBOL_BID) - op) / _Point;
      else
         pips = (op - SymbolInfoDouble(_Symbol, SYMBOL_ASK)) / _Point;
      
      // T1
      if(pips >= T1_Pips && !TicketInArray(t1_tickets, ticket))
      {
         double closeLots = NormalizeDouble(lots * T1_ClosePercent / 100.0, 2);
         if(closeLots < minLot) closeLots = minLot;
         if(closeLots >= lots) closeLots = lots - minLot;
         if(closeLots > 0)
         {
            if(trade.PositionClosePartial(ticket, closeLots))
            {
               AddTicketToArray(t1_tickets, ticket);
               Print("T1 hit #", ticket, " closed ", DoubleToString(closeLots,2));
            }
         }
      }
      
      // T2
      if(pips >= T2_Pips && !TicketInArray(t2_tickets, ticket))
      {
         if(!posInfo.SelectByTicket(ticket)) continue;
         lots = posInfo.Volume();
         double closeLots = NormalizeDouble(lots * T2_ClosePercent / 100.0, 2);
         if(closeLots < minLot) closeLots = minLot;
         if(closeLots >= lots) closeLots = lots - minLot;
         if(closeLots > 0)
         {
            if(trade.PositionClosePartial(ticket, closeLots))
            {
               AddTicketToArray(t2_tickets, ticket);
               Print("T2 hit #", ticket, " closed ", DoubleToString(closeLots,2));
            }
         }
      }
      
      // T3
      if(pips >= T3_Pips)
      {
         trade.PositionClose(ticket);
         Print("T3 hit #", ticket, " FULL CLOSE");
      }
   }
   CleanTicketArrays();
}

//+------------------------------------------------------------------+
//| Individual Trailing (after T2)                                    |
//+------------------------------------------------------------------+
void ManageIndividualTrailing()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      
      ulong ticket = posInfo.Ticket();
      if(!TicketInArray(t2_tickets, ticket)) continue;  // only after T2
      
      double op = posInfo.PriceOpen();
      double sl = posInfo.StopLoss();
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      
      if(posInfo.PositionType() == POSITION_TYPE_BUY)
      {
         double newSL = bid - Trail_Step_Pips * _Point;
         if(newSL > sl && newSL > op)
            trade.PositionModify(ticket, newSL, posInfo.TakeProfit());
      }
      else
      {
         double newSL = ask + Trail_Step_Pips * _Point;
         if((sl == 0 || newSL < sl) && newSL < op)
            trade.PositionModify(ticket, newSL, posInfo.TakeProfit());
      }
   }
}

//+------------------------------------------------------------------+
//| Basket Trailing                                                   |
//+------------------------------------------------------------------+
void ManageBasketTrailing()
{
   // Buy basket
   if(open_buy_count > 0)
   {
      if(!basketBuyActive && buyProfitPips >= Basket_Lock_Pips)
      {
         basketBuyActive = true;
         basketBuyHigh = buyProfitPips;
         basketBuyTrail = buyProfitPips - Basket_Trail_Step;
      }
      if(basketBuyActive)
      {
         if(buyProfitPips > basketBuyHigh)
         {
            basketBuyHigh = buyProfitPips;
            basketBuyTrail = basketBuyHigh - Basket_Trail_Step;
         }
         if(buyProfitPips <= basketBuyTrail)
         {
            CloseAllByType(POSITION_TYPE_BUY, "BasketTrail");
            basketBuyActive = false;
         }
      }
   }
   else { basketBuyActive = false; basketBuyHigh = 0; basketBuyTrail = 0; }
   
   // Sell basket
   if(open_sell_count > 0)
   {
      if(!basketSellActive && sellProfitPips >= Basket_Lock_Pips)
      {
         basketSellActive = true;
         basketSellHigh = sellProfitPips;
         basketSellTrail = sellProfitPips - Basket_Trail_Step;
      }
      if(basketSellActive)
      {
         if(sellProfitPips > basketSellHigh)
         {
            basketSellHigh = sellProfitPips;
            basketSellTrail = basketSellHigh - Basket_Trail_Step;
         }
         if(sellProfitPips <= basketSellTrail)
         {
            CloseAllByType(POSITION_TYPE_SELL, "BasketTrail");
            basketSellActive = false;
         }
      }
   }
   else { basketSellActive = false; basketSellHigh = 0; basketSellTrail = 0; }
}

//+------------------------------------------------------------------+
//| AMA Trend-Flip Exit                                              |
//+------------------------------------------------------------------+
void ManageAMAExit()
{
   if(open_buy_count == 0 && open_sell_count == 0) return;
   
   double ama[];
   ArraySetAsSeries(ama, true);
   if(CopyBuffer(ama_handle, 0, 0, 5, ama) < 5) return;
   
   double close[];
   ArraySetAsSeries(close, true);
   if(CopyClose(_Symbol, PERIOD_M1, 0, AMA_Confirm_Candles+1, close) < AMA_Confirm_Candles+1) return;
   
   // Bearish flip - close buys
   if(open_buy_count > 0)
   {
      int cnt = 0;
      for(int c = 1; c <= AMA_Confirm_Candles; c++)
         if(close[c] < ama[c]) cnt++;
      if(cnt >= AMA_Confirm_Candles)
      {
         CloseAllByType(POSITION_TYPE_BUY, "AMA_BearFlip");
         amaFlipBuy++;
         amaStatus = "BEAR FLIP";
      }
   }
   
   // Bullish flip - close sells
   if(open_sell_count > 0)
   {
      int cnt = 0;
      for(int c = 1; c <= AMA_Confirm_Candles; c++)
         if(close[c] > ama[c]) cnt++;
      if(cnt >= AMA_Confirm_Candles)
      {
         CloseAllByType(POSITION_TYPE_SELL, "AMA_BullFlip");
         amaFlipSell++;
         amaStatus = "BULL FLIP";
      }
   }
   
   prevAMA = ama[0];
}

//+------------------------------------------------------------------+
//| REVERSAL DETECTION EXIT SYSTEM                                   |
//| 5 confirmation checks:                                           |
//|  1. RSI Divergence                                               |
//|  2. MACD Histogram Reversal                                      |
//|  3. Volume Spike on counter-candle                               |
//|  4. EMA Cross-Back (price vs CTF 200 EMA)                       |
//|  5. ADX Trend Exhaustion                                         |
//+------------------------------------------------------------------+
void ManageReversalExit()
{
   if(open_buy_count == 0 && open_sell_count == 0) { reversal_buy_signals = 0; reversal_sell_signals = 0; return; }
   
   // Get RSI
   double rsi[];
   ArraySetAsSeries(rsi, true);
   if(CopyBuffer(rsi_handle, 0, 0, 20, rsi) < 20) return;
   
   // Get MACD histogram
   double macdHist[];
   ArraySetAsSeries(macdHist, true);
   if(CopyBuffer(macd_handle, 2, 0, 10, macdHist) < 10) return;
   
   // Get ADX
   double adx[];
   ArraySetAsSeries(adx, true);
   if(CopyBuffer(adx_handle, 0, 0, 10, adx) < 10) return;
   
   // Get Volume
   double vol[];
   ArraySetAsSeries(vol, true);
   if(CopyBuffer(vol_handle, 0, 0, Volume_Average_Periods+5, vol) < Volume_Average_Periods+5) return;
   
   // Get price
   double high[], low[], close[];
   ArraySetAsSeries(high, true);
   ArraySetAsSeries(low, true);
   ArraySetAsSeries(close, true);
   if(CopyHigh(_Symbol, Reversal_Timeframe, 0, 20, high) < 20) return;
   if(CopyLow(_Symbol, Reversal_Timeframe, 0, 20, low) < 20) return;
   if(CopyClose(_Symbol, Reversal_Timeframe, 0, 20, close) < 20) return;
   
   // Get EMA CTF
   double ema[];
   ArraySetAsSeries(ema, true);
   if(CopyBuffer(ema_ctf_handle, 0, 0, 5, ema) < 5) return;
   
   // --- BEARISH reversal (exit buys) ---
   if(open_buy_count > 0)
   {
      int sig = 0;
      // 1. RSI Divergence
      if(CheckRSIBearDiv(high, rsi)) sig++;
      // 2. MACD declining
      if(macdHist[1] < macdHist[2] && macdHist[2] < macdHist[3] && macdHist[3] > 0) sig++;
      else if(macdHist[1] < 0 && macdHist[2] > 0) sig++;
      // 3. Volume spike on down candle
      if(CheckBearVolSpike(vol, close)) sig++;
      // 4. Price cross back below EMA
      if(close[1] < ema[1] && close[2] >= ema[2]) sig++;
      // 5. ADX exhaustion
      if(CheckADXExhaustion(adx)) sig++;
      
      reversal_buy_signals = sig;
      if(sig >= Reversal_Min_Confirmations)
      {
         Print("REVERSAL EXIT [BEAR]: ", sig, "/5 signals - closing all BUYS");
         CloseAllByType(POSITION_TYPE_BUY, "Reversal_Bear");
      }
   }
   else reversal_buy_signals = 0;
   
   // --- BULLISH reversal (exit sells) ---
   if(open_sell_count > 0)
   {
      int sig = 0;
      // 1. RSI Divergence
      if(CheckRSIBullDiv(low, rsi)) sig++;
      // 2. MACD rising
      if(macdHist[1] > macdHist[2] && macdHist[2] > macdHist[3] && macdHist[3] < 0) sig++;
      else if(macdHist[1] > 0 && macdHist[2] < 0) sig++;
      // 3. Volume spike on up candle
      if(CheckBullVolSpike(vol, close)) sig++;
      // 4. Price cross back above EMA
      if(close[1] > ema[1] && close[2] <= ema[2]) sig++;
      // 5. ADX exhaustion
      if(CheckADXExhaustion(adx)) sig++;
      
      reversal_sell_signals = sig;
      if(sig >= Reversal_Min_Confirmations)
      {
         Print("REVERSAL EXIT [BULL]: ", sig, "/5 signals - closing all SELLS");
         CloseAllByType(POSITION_TYPE_SELL, "Reversal_Bull");
      }
   }
   else reversal_sell_signals = 0;
}

//+------------------------------------------------------------------+
//| RSI Bearish Divergence                                           |
//+------------------------------------------------------------------+
bool CheckRSIBearDiv(double &high[], double &rsi[])
{
   if(rsi[1] < RSI_OB_Level - 10 && rsi[2] < RSI_OB_Level - 10) return false;
   double pH1 = MathMax(high[1], MathMax(high[2], high[3]));
   double pH2 = MathMax(high[5], MathMax(high[6], MathMax(high[7], MathMax(high[8], high[9]))));
   double rH1 = MathMax(rsi[1], MathMax(rsi[2], rsi[3]));
   double rH2 = MathMax(rsi[5], MathMax(rsi[6], MathMax(rsi[7], MathMax(rsi[8], rsi[9]))));
   if(pH1 > pH2 && rH1 < rH2 - 2.0) return true;
   if(rsi[3] >= RSI_OB_Level && rsi[1] < RSI_OB_Level - 5.0) return true;
   return false;
}

//+------------------------------------------------------------------+
//| RSI Bullish Divergence                                           |
//+------------------------------------------------------------------+
bool CheckRSIBullDiv(double &low[], double &rsi[])
{
   if(rsi[1] > RSI_OS_Level + 10 && rsi[2] > RSI_OS_Level + 10) return false;
   double pL1 = MathMin(low[1], MathMin(low[2], low[3]));
   double pL2 = MathMin(low[5], MathMin(low[6], MathMin(low[7], MathMin(low[8], low[9]))));
   double rL1 = MathMin(rsi[1], MathMin(rsi[2], rsi[3]));
   double rL2 = MathMin(rsi[5], MathMin(rsi[6], MathMin(rsi[7], MathMin(rsi[8], rsi[9]))));
   if(pL1 < pL2 && rL1 > rL2 + 2.0) return true;
   if(rsi[3] <= RSI_OS_Level && rsi[1] > RSI_OS_Level + 5.0) return true;
   return false;
}

//+------------------------------------------------------------------+
//| Bearish Volume Spike                                             |
//+------------------------------------------------------------------+
bool CheckBearVolSpike(double &vol[], double &close[])
{
   double avg = 0;
   for(int v = 2; v < Volume_Average_Periods+2; v++) avg += vol[v];
   avg /= Volume_Average_Periods;
   if(avg <= 0) return false;
   return (close[1] < close[2] && vol[1] >= avg * Volume_Spike_Multiplier);
}

//+------------------------------------------------------------------+
//| Bullish Volume Spike                                             |
//+------------------------------------------------------------------+
bool CheckBullVolSpike(double &vol[], double &close[])
{
   double avg = 0;
   for(int v = 2; v < Volume_Average_Periods+2; v++) avg += vol[v];
   avg /= Volume_Average_Periods;
   if(avg <= 0) return false;
   return (close[1] > close[2] && vol[1] >= avg * Volume_Spike_Multiplier);
}

//+------------------------------------------------------------------+
//| ADX Trend Exhaustion                                             |
//+------------------------------------------------------------------+
bool CheckADXExhaustion(double &adx[])
{
   bool wasStrong = false;
   for(int a = 3; a < 8; a++)
      if(adx[a] >= ADX_Trend_Threshold) { wasStrong = true; break; }
   if(wasStrong && adx[1] < ADX_Weak_Threshold) return true;
   if(adx[1] < adx[2] && adx[2] < adx[3] && adx[3] >= ADX_Trend_Threshold) return true;
   return false;
}

//+------------------------------------------------------------------+
//| Close All By Type                                                 |
//+------------------------------------------------------------------+
void CloseAllByType(ENUM_POSITION_TYPE type, string reason)
{
   Print("CLOSE ALL ", EnumToString(type), " - ", reason);
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      if(posInfo.PositionType() != type) continue;
      trade.PositionClose(posInfo.Ticket());
   }
}

//+------------------------------------------------------------------+
//| Check Equity Protection                                           |
//+------------------------------------------------------------------+
bool CheckEquityProtection()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   if(bal <= 0) return false;
   
   double dd = ((bal - eq) / bal) * 100.0;
   double ddMoney = bal - eq;
   
   if(Use_EP_Percent && dd >= EP_Max_DD_Percent)
   {
      Print("EQUITY PROTECTION: DD ", DoubleToString(dd,2), "% - CLOSING ALL");
      CloseAllPositions("EP_Percent");
      return true;
   }
   if(Use_EP_Money && ddMoney >= EP_Max_DD_Money)
   {
      Print("EQUITY PROTECTION: DD $", DoubleToString(ddMoney,2), " - CLOSING ALL");
      CloseAllPositions("EP_Money");
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Master Equity Protection                                          |
//+------------------------------------------------------------------+
void CheckMasterEquityProtection()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   if(bal <= 0) return;
   double dd = ((bal - eq) / bal) * 100.0;
   
   bool trigger = (dd >= Master_Trigger_DD_Percent) || 
                  (open_buy_count + open_sell_count >= Master_Trigger_Min_Trades);
   
   // Buy side
   if(open_buy_count > 0 && trigger)
   {
      if(!masterBuyActive && buyProfitPips >= Master_Lock_Pips)
      {
         masterBuyActive = true;
         masterBuyHigh = buyProfitPips;
         masterBuyTrail = buyProfitPips - Master_Trail_Step;
      }
      if(masterBuyActive)
      {
         if(buyProfitPips > masterBuyHigh)
         {
            masterBuyHigh = buyProfitPips;
            masterBuyTrail = masterBuyHigh - Master_Trail_Step;
         }
         if(buyProfitPips <= masterBuyTrail)
         {
            CloseAllByType(POSITION_TYPE_BUY, "MasterEP");
            masterBuyActive = false;
         }
      }
   }
   else masterBuyActive = false;
   
   // Sell side
   if(open_sell_count > 0 && trigger)
   {
      if(!masterSellActive && sellProfitPips >= Master_Lock_Pips)
      {
         masterSellActive = true;
         masterSellHigh = sellProfitPips;
         masterSellTrail = sellProfitPips - Master_Trail_Step;
      }
      if(masterSellActive)
      {
         if(sellProfitPips > masterSellHigh)
         {
            masterSellHigh = sellProfitPips;
            masterSellTrail = masterSellHigh - Master_Trail_Step;
         }
         if(sellProfitPips <= masterSellTrail)
         {
            CloseAllByType(POSITION_TYPE_SELL, "MasterEP");
            masterSellActive = false;
         }
      }
   }
   else masterSellActive = false;
}

//+------------------------------------------------------------------+
//| Apply Master Trailing                                             |
//+------------------------------------------------------------------+
void ApplyMasterTrailing(ENUM_POSITION_TYPE type, double trailPips)
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      if(posInfo.PositionType() != type) continue;
      
      double op = posInfo.PriceOpen();
      double sl = posInfo.StopLoss();
      ulong tk = posInfo.Ticket();
      
      if(type == POSITION_TYPE_BUY)
      {
         double newSL = SymbolInfoDouble(_Symbol, SYMBOL_BID) - trailPips * _Point;
         if(newSL > sl && newSL > op)
            trade.PositionModify(tk, newSL, posInfo.TakeProfit());
      }
      else
      {
         double newSL = SymbolInfoDouble(_Symbol, SYMBOL_ASK) + trailPips * _Point;
         if((sl == 0 || newSL < sl) && newSL < op)
            trade.PositionModify(tk, newSL, posInfo.TakeProfit());
      }
   }
}

//+------------------------------------------------------------------+
//| Apply Trailing To Tickets                                         |
//+------------------------------------------------------------------+
void ApplyTrailingToTickets(ulong &tickets[], double trailPips)
{
   for(int i = 0; i < ArraySize(tickets); i++)
   {
      if(!posInfo.SelectByTicket(tickets[i])) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      
      double op = posInfo.PriceOpen();
      double sl = posInfo.StopLoss();
      
      if(posInfo.PositionType() == POSITION_TYPE_BUY)
      {
         double newSL = SymbolInfoDouble(_Symbol, SYMBOL_BID) - trailPips * _Point;
         if(newSL > sl && newSL > op)
            trade.PositionModify(tickets[i], newSL, posInfo.TakeProfit());
      }
      else
      {
         double newSL = SymbolInfoDouble(_Symbol, SYMBOL_ASK) + trailPips * _Point;
         if((sl == 0 || newSL < sl) && newSL < op)
            trade.PositionModify(tickets[i], newSL, posInfo.TakeProfit());
      }
   }
}

//+------------------------------------------------------------------+
//| Close All Positions                                               |
//+------------------------------------------------------------------+
void CloseAllPositions(string reason)
{
   Print("CLOSE ALL - ", reason);
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      trade.PositionClose(posInfo.Ticket());
   }
}

//+------------------------------------------------------------------+
//| Ticket Array Helpers                                              |
//+------------------------------------------------------------------+
bool TicketInArray(ulong &arr[], ulong ticket)
{
   for(int i = 0; i < ArraySize(arr); i++)
      if(arr[i] == ticket) return true;
   return false;
}

void AddTicketToArray(ulong &arr[], ulong ticket)
{
   int sz = ArraySize(arr);
   ArrayResize(arr, sz+1);
   arr[sz] = ticket;
}

void CleanTicketArrays()
{
   // Remove tickets no longer in positions
   for(int i = ArraySize(t1_tickets)-1; i >= 0; i--)
   {
      bool found = false;
      for(int j = PositionsTotal()-1; j >= 0; j--)
      {
         if(posInfo.SelectByIndex(j) && posInfo.Ticket() == t1_tickets[i])
         { found = true; break; }
      }
      if(!found)
      {
         int last = ArraySize(t1_tickets)-1;
         t1_tickets[i] = t1_tickets[last];
         ArrayResize(t1_tickets, last);
      }
   }
   for(int i = ArraySize(t2_tickets)-1; i >= 0; i--)
   {
      bool found = false;
      for(int j = PositionsTotal()-1; j >= 0; j--)
      {
         if(posInfo.SelectByIndex(j) && posInfo.Ticket() == t2_tickets[i])
         { found = true; break; }
      }
      if(!found)
      {
         int last = ArraySize(t2_tickets)-1;
         t2_tickets[i] = t2_tickets[last];
         ArrayResize(t2_tickets, last);
      }
   }
}

//+------------------------------------------------------------------+
//| Detect Bullish Pattern                                            |
//+------------------------------------------------------------------+
int DetectBullishPattern()
{
   double open[], high[], low[], close[];
   ArraySetAsSeries(open, true);
   ArraySetAsSeries(high, true);
   ArraySetAsSeries(low, true);
   ArraySetAsSeries(close, true);
   if(CopyOpen(_Symbol, Trade_Timeframe, 0, 10, open) < 10) return 0;
   if(CopyHigh(_Symbol, Trade_Timeframe, 0, 10, high) < 10) return 0;
   if(CopyLow(_Symbol, Trade_Timeframe, 0, 10, low) < 10) return 0;
   if(CopyClose(_Symbol, Trade_Timeframe, 0, 10, close) < 10) return 0;
   
   double body1 = MathAbs(close[1]-open[1]);
   double range1 = high[1]-low[1];
   if(range1 == 0) return 0;
   double body2 = MathAbs(close[2]-open[2]);
   
   if(Use_Hammer)
   {
      double ls = MathMin(open[1],close[1])-low[1];
      double us = high[1]-MathMax(open[1],close[1]);
      if(ls > body1*2 && us < body1*0.3 && close[1] > open[1]) return 1;
   }
   if(Use_InvHammer)
   {
      double ls = MathMin(open[1],close[1])-low[1];
      double us = high[1]-MathMax(open[1],close[1]);
      if(us > body1*2 && ls < body1*0.3 && close[2] < open[2]) return 2;
   }
   if(Use_BullEngulf)
   {
      if(close[2]<open[2] && close[1]>open[1] && close[1]>open[2] && open[1]<close[2]) return 3;
   }
   if(Use_PiercingLine)
   {
      if(close[2]<open[2] && close[1]>open[1] && open[1]<low[2] && close[1]>(open[2]+close[2])/2.0) return 4;
   }
   if(Use_MorningStar)
   {
      double body3 = MathAbs(close[3]-open[3]);
      if(close[3]<open[3] && body2<body3*0.3 && close[1]>open[1] && close[1]>(open[3]+close[3])/2.0) return 5;
   }
   if(Use_ThreeWhite)
   {
      if(close[1]>open[1] && close[2]>open[2] && close[3]>open[3] && close[1]>close[2] && close[2]>close[3]) return 6;
   }
   if(Use_BullHarami)
   {
      if(close[2]<open[2] && close[1]>open[1] && high[1]<open[2] && low[1]>close[2]) return 7;
   }
   if(Use_Doji)
   {
      if(body1 < range1*0.1 && close[2]<open[2]) return 8;
   }
   if(Use_DoubleBottom)
   {
      double tol = range1*0.5;
      if(MathAbs(low[1]-low[5])<tol && low[3]>low[1]+tol) return 9;
   }
   if(Use_InvHeadShould)
   {
      if(low[2]<low[4] && low[2]<low[6] && MathAbs(low[4]-low[6])<(low[4]-low[2])*0.5) return 10;
   }
   if(Use_BullFlag)
   {
      double mv = close[5]-close[9]; double pb = close[5]-close[1];
      if(mv>0 && pb>0 && pb<mv*0.38 && close[1]>open[1]) return 11;
   }
   if(Use_FallingWedge)
   {
      double hs = high[5]-high[1]; double ls2 = low[5]-low[1];
      if(hs>0 && ls2>0 && ls2>hs) return 12;
   }
   if(Use_BullTriangle)
   {
      double tol = range1*0.3;
      if(MathAbs(high[1]-high[5])<tol && low[1]>low[5]) return 13;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| Detect Bearish Pattern                                            |
//+------------------------------------------------------------------+
int DetectBearishPattern()
{
   double open[], high[], low[], close[];
   ArraySetAsSeries(open, true);
   ArraySetAsSeries(high, true);
   ArraySetAsSeries(low, true);
   ArraySetAsSeries(close, true);
   if(CopyOpen(_Symbol, Trade_Timeframe, 0, 10, open) < 10) return 0;
   if(CopyHigh(_Symbol, Trade_Timeframe, 0, 10, high) < 10) return 0;
   if(CopyLow(_Symbol, Trade_Timeframe, 0, 10, low) < 10) return 0;
   if(CopyClose(_Symbol, Trade_Timeframe, 0, 10, close) < 10) return 0;
   
   double body1 = MathAbs(close[1]-open[1]);
   double range1 = high[1]-low[1];
   if(range1 == 0) return 0;
   double body2 = MathAbs(close[2]-open[2]);
   
   if(Use_ShootingStar)
   {
      double us = high[1]-MathMax(open[1],close[1]);
      double ls = MathMin(open[1],close[1])-low[1];
      if(us > body1*2 && ls < body1*0.3 && close[1]<open[1]) return 1;
   }
   if(Use_BearEngulf)
   {
      if(close[2]>open[2] && close[1]<open[1] && close[1]<open[2] && open[1]>close[2]) return 2;
   }
   if(Use_EveningStar)
   {
      double body3 = MathAbs(close[3]-open[3]);
      if(close[3]>open[3] && body2<body3*0.3 && close[1]<open[1] && close[1]<(open[3]+close[3])/2.0) return 3;
   }
   if(Use_ThreeBlack)
   {
      if(close[1]<open[1] && close[2]<open[2] && close[3]<open[3] && close[1]<close[2] && close[2]<close[3]) return 4;
   }
   if(Use_DarkCloud)
   {
      if(close[2]>open[2] && close[1]<open[1] && open[1]>high[2] && close[1]<(open[2]+close[2])/2.0) return 5;
   }
   if(Use_BearHarami)
   {
      if(close[2]>open[2] && close[1]<open[1] && high[1]<close[2] && low[1]>open[2]) return 6;
   }
   if(Use_HangingMan)
   {
      double ls = MathMin(open[1],close[1])-low[1];
      double us = high[1]-MathMax(open[1],close[1]);
      if(ls > body1*2 && us < body1*0.3 && close[1]<open[1]) return 7;
   }
   if(Use_Doji)
   {
      if(body1 < range1*0.1 && close[2]>open[2]) return 8;
   }
   if(Use_DoubleTop)
   {
      double tol = range1*0.5;
      if(MathAbs(high[1]-high[5])<tol && high[3]<high[1]-tol) return 9;
   }
   if(Use_HeadShoulders)
   {
      if(high[2]>high[4] && high[2]>high[6] && MathAbs(high[4]-high[6])<(high[2]-high[4])*0.5) return 10;
   }
   if(Use_BearFlag)
   {
      double mv = close[9]-close[5]; double pb = close[1]-close[5];
      if(mv>0 && pb>0 && pb<mv*0.38 && close[1]<open[1]) return 11;
   }
   if(Use_RisingWedge)
   {
      double hs = high[1]-high[5]; double ls2 = low[1]-low[5];
      if(hs>0 && ls2>0 && ls2>hs) return 12;
   }
   if(Use_BearTriangle)
   {
      double tol = range1*0.3;
      if(MathAbs(low[1]-low[5])<tol && high[1]<high[5]) return 13;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| News Time Check (placeholder)                                     |
//+------------------------------------------------------------------+
bool IsNewsTime()
{
   // Placeholder - returns false (no calendar access in backtest)
   return false;
}

//+------------------------------------------------------------------+
//| Get Period PnL                                                    |
//+------------------------------------------------------------------+
double GetPeriodPnL(datetime from, datetime to)
{
   double pnl = 0;
   HistorySelect(from, to);
   for(int i = HistoryDealsTotal()-1; i >= 0; i--)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != Magic_Number) continue;
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      pnl += HistoryDealGetDouble(ticket, DEAL_PROFIT) + 
             HistoryDealGetDouble(ticket, DEAL_SWAP) + 
             HistoryDealGetDouble(ticket, DEAL_COMMISSION);
   }
   return pnl;
}

//+------------------------------------------------------------------+
//| Refresh PnL Cache                                                 |
//+------------------------------------------------------------------+
void RefreshPnLCache()
{
   datetime now = TimeCurrent();
   if(now - pnl_cache_time < 60) return;
   pnl_cache_time = now;
   
   MqlDateTime dt;
   TimeToStruct(now, dt);
   
   // Today
   datetime todayStart = now - dt.hour*3600 - dt.min*60 - dt.sec;
   pnl_today = GetPeriodPnL(todayStart, now);
   
   // Yesterday
   datetime yestStart = todayStart - 86400;
   pnl_yesterday = GetPeriodPnL(yestStart, todayStart);
   
   // This week (Monday start)
   int dow = dt.day_of_week;
   if(dow == 0) dow = 7;
   datetime weekStart = todayStart - (dow-1)*86400;
   pnl_week = GetPeriodPnL(weekStart, now);
   
   // This month
   datetime monthStart = todayStart - (dt.day-1)*86400;
   pnl_month = GetPeriodPnL(monthStart, now);
   
   // Last month
   datetime lastMonthEnd = monthStart;
   datetime lastMonthStart = lastMonthEnd - 30*86400;  // approximate
   MqlDateTime lmDt;
   TimeToStruct(lastMonthEnd - 86400, lmDt);
   lastMonthStart = lastMonthEnd - lmDt.day * 86400;
   pnl_last_month = GetPeriodPnL(lastMonthStart, lastMonthEnd);
}

//+------------------------------------------------------------------+
//| CREATE DASHBOARD                                                  |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   DeleteDashboard();
   int x = Dashboard_X, y = Dashboard_Y;

   // --- Colours matching OFT TrendTrading style ---
   color bg_col     = C'22,30,45';    // dark blue-grey panel
   color border_col = C'45,55,90';    // medium blue border
   color lbl_col    = clrSilver;
   color val_col    = clrWhite;
   int   lfs        = 8;              // label font size
   int   vx         = x + 100;        // value column X
   int   row        = 14;             // row height

   // Background — taller to fit all rows
   ObjRect(lbl+"bg", x-8, y-8, 325, 460, bg_col, border_col, 1);

   // Title row — orange square bullet like OFT
   ObjLabel(lbl+"bullet", "\x25A0", x, y+2, C'255,140,0', 10, true);
   ObjLabel(lbl+"title",  " GaganEA v2.10", x+12, y+2, clrWhite, 9, true);
   ObjLine(lbl+"d0", x, y+18, 305);
   
   // --- Symbol / TF block ---
   int r = y+28;
   ObjLabel(lbl+"l_sym",  "Symbol",   x,  r,        lbl_col, lfs);
   ObjLabel(lbl+"v_sym",  _Symbol,    vx, r,        val_col, lfs);
   ObjLabel(lbl+"l_ttf",  "Trade TF", x,  r+row,    lbl_col, lfs);
   ObjLabel(lbl+"v_ttf",  TFStr(Trade_Timeframe), vx, r+row, val_col, lfs);
   ObjLabel(lbl+"l_htf",  "HTF",      x,  r+row*2,  lbl_col, lfs);
   ObjLabel(lbl+"v_htf",  TFStr(HTF_Timeframe),   vx, r+row*2, val_col, lfs);
   ObjLine(lbl+"d1", x, r+row*3+2, 305);

   // --- Trend / Signal block ---
   r = y+28 + row*3 + 12;
   ObjLabel(lbl+"l_trend","HTF Trend",  x,  r,        lbl_col, lfs);
   ObjLabel(lbl+"v_trend","---",        vx, r,        val_col, lfs);
   ObjLabel(lbl+"l_ctf",  "CTF EMA",   x,  r+row,    lbl_col, lfs);
   ObjLabel(lbl+"v_ctf",  "---",       vx, r+row,    val_col, lfs);
   ObjLabel(lbl+"l_dist", "Distance",  x,  r+row*2,  lbl_col, lfs);
   ObjLabel(lbl+"v_dist", "---",       vx, r+row*2,  val_col, lfs);
   ObjLabel(lbl+"l_sig",  "Signal",    x,  r+row*3,  lbl_col, lfs);
   ObjLabel(lbl+"v_sig",  "---",       vx, r+row*3,  val_col, lfs);
   ObjLabel(lbl+"l_sprd", "Spread",    x,  r+row*4,  lbl_col, lfs);
   ObjLabel(lbl+"v_sprd", "---",       vx, r+row*4,  val_col, lfs);
   ObjLine(lbl+"d2", x, r+row*5+2, 305);
   
   // --- Trade block ---
   r = r + row*5 + 12;
   ObjLabel(lbl+"l_open", "Open Trades",  x,  r,        lbl_col, lfs);
   ObjLabel(lbl+"v_open", "0",            vx, r,        val_col, lfs);
   ObjLabel(lbl+"l_lot",  "Lot Size",     x,  r+row,    lbl_col, lfs);
   ObjLabel(lbl+"v_lot",  "---",          vx, r+row,    val_col, lfs);
   ObjLabel(lbl+"l_fpnl", "Floating P/L", x,  r+row*2,  lbl_col, lfs);
   ObjLabel(lbl+"v_fpnl", "---",          vx, r+row*2,  val_col, lfs);
   ObjLine(lbl+"d3", x, r+row*3+2, 305);

   // SL/T info + Lot Mode (single compact line each)
   r = r + row*3 + 10;
   ObjLabel(lbl+"l_slinfo", StringFormat("SL: %d  |  T1:%d  |  T2:%d  |  T3:%d",
            StopLoss_Pips, T1_Pips, T2_Pips, T3_Pips), x, r, lbl_col, lfs);
   ObjLabel(lbl+"l_lm",  "Lot Mode",  x,   r+row,  lbl_col, lfs);
   ObjLabel(lbl+"v_lm",  Manual_LotSize > 0
            ? StringFormat("Manual %.2f", Manual_LotSize)
            : StringFormat("Auto %.1f%%", Risk_Percent), vx, r+row, val_col, lfs);
   ObjLine(lbl+"d4", x, r+row*2+4, 305);
   
   // --- P&L block (paired like OFT: Today | Yest on same line) ---
   r = r + row*2 + 14;
   ObjLabel(lbl+"l_today", "Today :",    x,       r,       lbl_col, lfs);
   ObjLabel(lbl+"v_today", "---",        x+55,    r,       val_col, lfs);
   ObjLabel(lbl+"l_yest",  "| Yest :",   x+150,   r,       lbl_col, lfs);
   ObjLabel(lbl+"v_yest",  "---",        x+210,   r,       val_col, lfs);

   ObjLabel(lbl+"l_week",  "This Week :",x,       r+row,   lbl_col, lfs);
   ObjLabel(lbl+"v_week",  "---",        x+75,    r+row,   val_col, lfs);
   ObjLabel(lbl+"l_mo",    "| This Mo :",x+150,   r+row,   lbl_col, lfs);
   ObjLabel(lbl+"v_mo",    "---",        x+215,   r+row,   val_col, lfs);

   ObjLabel(lbl+"l_lmo",   "Last Month :",x,      r+row*2, lbl_col, lfs);
   ObjLabel(lbl+"v_lmo",   "---",         x+80,   r+row*2, val_col, lfs);
   ObjLine(lbl+"d5", x, r+row*3+2, 305);
   
   // --- News + Last Bar block ---
   r = r + row*3 + 12;
   ObjLabel(lbl+"l_news", "News Filter",  x,  r,       lbl_col, lfs);
   ObjLabel(lbl+"v_news", "OFF \xE2\x9C\x93", vx, r,  clrLime,  lfs);
   ObjLabel(lbl+"l_bar",  "Last Bar",     x,  r+row,   lbl_col, lfs);
   ObjLabel(lbl+"v_bar",  "---",          vx, r+row,   val_col, lfs);
   ObjLine(lbl+"d6", x, r+row*2+4, 305);

   // --- AMA Exit block (M1 trend-flip) ---
   r = r + row*2 + 12;
   ObjLabel(lbl+"l_ama",  "AMA Exit (M1)", x,  r,       lbl_col, lfs);
   ObjLabel(lbl+"v_ama",  Use_AMA_Exit ? "ON" : "OFF",  vx, r,  Use_AMA_Exit ? clrLime : clrGray, lfs);
   ObjLabel(lbl+"l_amast",   "Flip Status",  x,  r+row,   lbl_col, lfs);
   ObjLabel(lbl+"v_amast",   "---",          vx, r+row,   val_col, lfs);
   ObjLine(lbl+"d7", x, r+row*2+4, 305);
   
   // --- Reversal Detection block (NEW - added for reversal exit) ---
   r = r + row*2 + 12;
   ObjLabel(lbl+"l_rev",  "Reversal Exit", x,  r,       lbl_col, lfs);
   ObjLabel(lbl+"v_rev",  Use_Reversal_Exit ? "ON" : "OFF",  vx, r,  Use_Reversal_Exit ? clrLime : clrGray, lfs);
   ObjLabel(lbl+"l_revst",   "Rev Status",  x,  r+row,   lbl_col, lfs);
   ObjLabel(lbl+"v_revst",   "---",          vx, r+row,   val_col, lfs);
   ObjLine(lbl+"d8", x, r+row*2+4, 305);

   // --- Status ---
   r = r + row*2 + 12;
   ObjLabel(lbl+"l_sta",  "Status",    x,  r, lbl_col, lfs);
   ObjLabel(lbl+"v_sta",  "RUNNING",   vx, r, clrLime,  lfs);

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| UPDATE DASHBOARD                                                  |
//+------------------------------------------------------------------+
void UpdateDashboard()
{
   if(!Show_Dashboard) return;

   // HTF trend
   string trend_str = htf_bullish ? "\x25B2 BULLISH" : (htf_bearish ? "\x25BC BEARISH" : "NEUTRAL");
   color  trend_col = htf_bullish ? clrLime : (htf_bearish ? clrTomato : clrWhite);
   ObjSetText(lbl+"v_trend", trend_str, trend_col);

   // CTF
   string ctf_str = ctf_above_ema ? "Above EMA (BUY zone)" : "Below EMA (SELL zone)";
   ObjSetText(lbl+"v_ctf", ctf_str, ctf_above_ema ? clrLime : clrTomato);

   // Distance
   string dist_suffix = (ema_distance_pips >= Min_EMA_Distance) ? " pips OK" : " pips LOW";
   ObjSetText(lbl+"v_dist", StringFormat("%.1f%s", ema_distance_pips, dist_suffix),
              (ema_distance_pips >= Min_EMA_Distance) ? clrLime : clrOrange);

   // Signal
   ObjSetText(lbl+"v_sig", current_signal, signal_color);

   // Live spread
   double live_spread = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID)) / pip;
   color sprd_col = (Max_Spread_Pips > 0 && live_spread > Max_Spread_Pips) ? clrTomato : clrLime;
   ObjSetText(lbl+"v_sprd", StringFormat("%.1f pips%s", live_spread,
              (Max_Spread_Pips > 0 && live_spread > Max_Spread_Pips) ? " WIDE!" : " OK"), sprd_col);

   // Open trades
   ObjSetText(lbl+"v_open", StringFormat("%d (B:%d S:%d)",
              open_buy_count + open_sell_count, open_buy_count, open_sell_count), clrWhite);

   // Lot size
   ObjSetText(lbl+"v_lot", StringFormat("%.2f", CalcLotSize()), clrWhite);

   // Floating P&L
   ObjSetText(lbl+"v_fpnl", StringFormat("%.2f", floating_pnl),
              floating_pnl >= 0 ? clrLime : clrTomato);

   // Period P&L (cached)
   RefreshPnLCache();
   ObjSetText(lbl+"v_today", StringFormat("USD %.2f", pnl_today),  pnl_today  >= 0 ? clrLime : clrTomato);
   ObjSetText(lbl+"v_yest",  StringFormat("USD %.2f", pnl_yesterday), clrWhite);
   ObjSetText(lbl+"v_week",  StringFormat("USD %.2f", pnl_week),   pnl_week   >= 0 ? clrLime : clrTomato);
   ObjSetText(lbl+"v_mo",    StringFormat("USD %.2f", pnl_month),  pnl_month  >= 0 ? clrLime : clrTomato);
   ObjSetText(lbl+"v_lmo",   StringFormat("USD %.2f", pnl_last_month), clrWhite);

   // News
   string news_str = News_Filter_Enable ? (news_active ? "ACTIVE!" : "ON") : "OFF";
   ObjSetText(lbl+"v_news", news_str, news_active ? clrOrange : clrLime);

   // Last bar
   ObjSetText(lbl+"v_bar", TimeToString(last_bar_time, TIME_DATE|TIME_MINUTES), clrWhite);

   // AMA Exit flip status
   UpdateAMADashboard();

   // Reversal Detection status (NEW)
   if(Use_Reversal_Exit)
   {
      int maxSig = MathMax(reversal_buy_signals, reversal_sell_signals);
      string revStr;
      color revCol;
      if(maxSig >= Reversal_Min_Confirmations) { revStr = IntegerToString(maxSig) + "/5 TRIGGERED"; revCol = clrRed; }
      else if(maxSig >= 1) { revStr = IntegerToString(maxSig) + "/5 ALERT"; revCol = clrOrange; }
      else { revStr = "0/5 Safe"; revCol = clrLime; }
      ObjSetText(lbl+"v_revst", revStr, revCol);
   }
   else
      ObjSetText(lbl+"v_revst", "DISABLED", clrGray);

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Update AMA Dashboard Section                                      |
//+------------------------------------------------------------------+
void UpdateAMADashboard()
{
   if(!Use_AMA_Exit) { ObjSetText(lbl+"v_amast", "DISABLED", clrGray); return; }
   if(open_buy_count == 0 && open_sell_count == 0) { ObjSetText(lbl+"v_amast", "No Position", clrGray); return; }

   int need = MathMax(1, AMA_Confirm_Candles);
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(ama_handle, 0, 1, need, buf) < need)
   {
      ObjSetText(lbl+"v_amast", "---", clrGray);
      return;
   }

   if(open_buy_count > 0)
   {
      int count_against = 0;
      for(int i = 0; i < need; i++)
      {
         double close_px = iClose(_Symbol, PERIOD_M1, i + 1);
         if(close_px < buf[i]) count_against++;
         else break;
      }
      ObjSetText(lbl+"v_amast", StringFormat("BUY %d/%d below", count_against, need),
                 count_against >= need ? clrTomato : clrYellow);
   }
   else if(open_sell_count > 0)
   {
      int count_against = 0;
      for(int i = 0; i < need; i++)
      {
         double close_px = iClose(_Symbol, PERIOD_M1, i + 1);
         if(close_px > buf[i]) count_against++;
         else break;
      }
      ObjSetText(lbl+"v_amast", StringFormat("SELL %d/%d above", count_against, need),
                 count_against >= need ? clrTomato : clrYellow);
   }
}

//+------------------------------------------------------------------+
//| DASHBOARD HELPER FUNCTIONS                                        |
//+------------------------------------------------------------------+
void ObjLabel(string name, string text, int x, int y, color clr, int fs=8, bool bold=false)
{
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0,  name, OBJPROP_TEXT,      text);
   ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,  fs);
   ObjectSetString(0,  name, OBJPROP_FONT,      bold ? "Arial Bold" : "Arial");
   ObjectSetInteger(0, name, OBJPROP_BACK,      false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,false);
}

void ObjSetText(string name, string text, color clr)
{
   if(ObjectFind(0, name) < 0) return;
   ObjectSetString(0,  name, OBJPROP_TEXT,  text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
}

void ObjLine(string name, int x, int y, int width)
{
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   string dashes = "";
   int count = (int)(width / 5.5);
   for(int i = 0; i < count; i++) dashes += "-";
   ObjectSetInteger(0, name, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0,  name, OBJPROP_TEXT,      dashes);
   ObjectSetInteger(0, name, OBJPROP_COLOR,     C'45,55,90');
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,  6);
   ObjectSetString(0,  name, OBJPROP_FONT,      "Arial");
   ObjectSetInteger(0, name, OBJPROP_BACK,      false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,false);
}

void ObjRect(string name, int x, int y, int w, int h, color bg, color border, int bwidth)
{
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER,      CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE,   x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE,   y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE,       w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE,       h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR,     bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_COLOR,       border);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,       bwidth);
   ObjectSetInteger(0, name, OBJPROP_BACK,        false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,  false);
}

void DeleteDashboard() { ObjectsDeleteAll(0, lbl); }

string TFStr(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1:  return "M1";  case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15"; case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";  case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";  case PERIOD_W1:  return "W1";
      case PERIOD_MN1: return "MN";  default:         return "?";
   }
}
//+------------------------------------------------------------------+
