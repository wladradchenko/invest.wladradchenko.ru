"""
Weekly advisor pipeline (runs inside the celery worker).

Saturday: full report — sync data, evaluate LAST week's recommendations
against reality (which strategy component was wrong and by how much),
compute regime/allocation and per-asset actions, store everything for the
/summary page and the JSON export.

Thursday: midweek check — intermediate report that flags recommendations
moving strongly against us (alarms) without regenerating the whole plan.
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from cache import CacheManager
from cbr_api import fetch_key_rate_history, rate_now_and_3m_ago
from database import Database
from ml_models import MLPredictor
from moex_api import MOEXClient
from settings import CONFIG
import strategy

logger = logging.getLogger("advisor")

INDEX_BOARD = {"engine": "stock", "market": "index", "board": "SNDX"}
HISTORY_DAYS = 400  # ~13 months of daily candles for 12-1 momentum


def make_throttle(delay: float = 0.5):
    """Sequential throttle: at most ~1/delay real HTTP requests per second"""
    sem = asyncio.Semaphore(1)

    async def throttle():
        async with sem:
            await asyncio.sleep(delay)

    return throttle


def build_universe(equities: List[str]) -> List[Dict]:
    cfg = CONFIG["advisor"]
    universe = [{"secid": s, "asset_class": "equity"} for s in equities]
    universe += [{"secid": b, "asset_class": "bond"} for b in cfg["bonds"]]
    universe.append({"secid": cfg["money_market"], "asset_class": "money_market"})
    universe.append({"secid": cfg["gold"], "asset_class": "gold",
                     "fallback": cfg.get("gold_fallback")})
    return universe


async def sync_candles(client: MOEXClient, db: Database,
                       secid: str, board_market: Optional[Dict] = None) -> bool:
    """Incremental candle sync: fetch only newer than the last stored candle."""
    last_date = await db.get_last_candle_date(secid)
    from_date = last_date  # MOEX includes the boundary date; INSERT OR IGNORE dedups
    days = HISTORY_DAYS if not last_date else None

    if board_market is None:
        board_market = await client.get_security_board_market(secid, db=db)
    if not board_market:
        board_market = {"board": "TQBR", "market": "shares", "engine": "stock"}

    candles = await client.get_candles(
        secid,
        board=board_market.get("board", "TQBR"),
        market=board_market.get("market", "shares"),
        engine=board_market.get("engine", "stock"),
        days=days or HISTORY_DAYS,
        from_date=from_date,
        use_cache=False,
    )

    if candles:
        await db.insert_candles(candles)
        return True
    # Existing history still counts as data
    return last_date is not None


async def compute_dividend_yield(client: MOEXClient, secid: str,
                                 price: Optional[float]) -> Optional[float]:
    """Trailing 12m dividends / current price, as a fraction"""
    if not price or price <= 0:
        return None
    try:
        dividends = await client.get_dividends(secid)
    except Exception:
        return None
    if not dividends:
        return None
    cutoff = datetime.now().replace(year=datetime.now().year - 1).date().isoformat()
    total = 0.0
    for div in dividends:
        date = div.get("registryclosedate") or ""
        value = div.get("value")
        if date >= cutoff and value:
            total += float(value)
    return total / price if total > 0 else None


async def evaluate_previous_report(db: Database, week_start: str,
                                   benchmark_return: Optional[float]) -> Optional[Dict]:
    """Fill realized returns / hits on last week's recommendations and build
    the component-level error analysis."""
    previous = await db.get_unevaluated_weekly_report(before_week=week_start)
    if not previous:
        return None

    evaluated = []
    for reco in previous["recommendations"]:
        price_at_reco = reco.get("price_at_reco")
        latest = await db.get_latest_close(reco["secid"])
        if not price_at_reco or not latest or not latest.get("close"):
            continue
        price_now = latest["close"]
        realized = price_now / price_at_reco - 1.0
        hit = strategy.evaluate_hit(reco["action"], realized)
        in_zone = None
        if reco.get("forecast_low") is not None and reco.get("forecast_high") is not None:
            in_zone = int(reco["forecast_low"] <= price_now <= reco["forecast_high"])
        await db.mark_recommendation_evaluated(
            reco["id"], price_now, round(realized, 6), hit, in_zone)
        evaluated.append({
            "secid": reco["secid"],
            "action": reco["action"],
            "components": {**reco.get("components", {})},
            "realized_return": realized,
            "hit": hit,
            "in_zone": in_zone,
        })

    if not evaluated:
        return None

    report = strategy.component_report(evaluated, benchmark_return)
    report["evaluated_report_id"] = previous["id"]
    report["evaluated_week_start"] = previous["week_start"]
    # Details per recommendation for the "forecast vs fact" chart
    report["details"] = [
        {
            "secid": e["secid"],
            "action": e["action"],
            "realized_return": round(e["realized_return"], 4),
            "hit": e["hit"],
            "in_zone": e["in_zone"],
        }
        for e in sorted(evaluated, key=lambda x: x["realized_return"])
    ]
    return report


def weekly_index_return(closes: List[float]) -> Optional[float]:
    if len(closes) < 6:
        return None
    return closes[-1] / closes[-6] - 1.0


async def run_weekly_pipeline(week_start: str = None):
    cfg = CONFIG["advisor"]
    week_start = week_start or datetime.now().date().isoformat()
    logger.info(f"Weekly advisor pipeline started for {week_start}")

    db = Database()
    await db.init_db()
    cache = CacheManager()
    predictor = MLPredictor()

    failed: List[str] = []

    async with MOEXClient(cache_manager=cache, throttle=make_throttle(0.5)) as client:
        # 1-2. CBR key rate (7-day cache, fallback to last known)
        rate_history = await fetch_key_rate_history(months=4, cache=cache)
        cbr_rate, cbr_rate_3m_ago = rate_now_and_3m_ago(rate_history)

        # 3. Universe: index constituents + bonds + money market + gold
        index_rows = await client.get_index_securities(cfg["index"])
        equities = [r.get("ticker") for r in index_rows if r.get("ticker")]
        if not equities:
            logger.error("Could not load index constituents, aborting")
            raise RuntimeError("empty universe")
        universe = build_universe(equities)

        # 4. Index monthly candles for the 10-month SMA regime
        index_monthly = await client.get_candles(
            cfg["index"], interval=31, days=420, use_cache=False, **INDEX_BOARD)
        index_monthly_closes = [c["close"] for c in index_monthly if c.get("close")]

        # Index daily candles (benchmark for evaluation)
        await db.insert_candles(await client.get_candles(
            cfg["index"], interval=24, days=30, use_cache=False, **INDEX_BOARD))

        # 5. Incremental candle sync (throttled)
        for asset in universe:
            secid = asset["secid"]
            try:
                ok = await sync_candles(client, db, secid)
                if not ok and asset.get("fallback"):
                    logger.info(f"{secid}: trying fallback instrument {asset['fallback']}")
                    asset["secid"] = asset["fallback"]
                    ok = await sync_candles(client, db, asset["secid"])
                if not ok:
                    failed.append(secid)
                    asset["data_missing"] = True
            except Exception as e:
                logger.error(f"Candle sync failed for {secid}: {e}")
                failed.append(secid)
                asset["data_missing"] = True

        # 6. Evaluate the PREVIOUS report against reality
        index_closes = await db.get_closes(cfg["index"], days=30)
        benchmark = weekly_index_return(index_closes)
        evaluation = await evaluate_previous_report(db, week_start, benchmark)

        # 7. Regime and allocation
        reg = strategy.regime(index_monthly_closes, cbr_rate, cbr_rate_3m_ago,
                              high_rate_level=cfg["high_rate_level"])
        alloc = strategy.allocation(reg)

        # Previous actions for hysteresis
        prev_actions: Dict[str, str] = {}
        latest_report = await db.get_latest_weekly_report()
        if latest_report:
            prev_actions = {r["secid"]: r["action"]
                            for r in latest_report["recommendations"]}

        # 8. Per-asset components
        assets: List[Dict] = []
        for asset in universe:
            secid = asset["secid"]
            entry = {**asset, "components": {}}
            if asset.get("data_missing"):
                entry["components"]["data_missing"] = True
                assets.append(entry)
                continue

            closes = await db.get_closes(secid, days=HISTORY_DAYS + 50)
            if len(closes) < 30:
                entry["components"]["data_missing"] = True
                assets.append(entry)
                continue

            mom = strategy.tsmom(closes)
            vol = strategy.ann_vol(closes)
            entry["price"] = closes[-1]
            entry["closes"] = closes
            entry["components"].update({
                "m3": mom["m3"],
                "m12_1": mom["m12_1"],
                "vol_ann": round(vol, 4) if vol is not None else None,
                "vol_scaled_m3": strategy.vol_scaled_momentum(mom["m3"], vol),
            })

            if asset["asset_class"] == "equity":
                div_yield = await compute_dividend_yield(client, secid, entry["price"])
                sent_raw = await db.get_mean_sentiment(secid, days=14)
                entry["components"]["div_yield"] = round(div_yield, 4) if div_yield else None
                entry["components"]["sentiment_posts"] = sent_raw["n"]
                entry["components"]["sentiment"] = strategy.sentiment_score(
                    sent_raw["positive"], sent_raw["negative"], sent_raw["n"],
                    min_posts=cfg["sentiment_min_posts"])
            assets.append(entry)

    # Cross-sectional ranks over equities only
    equity_assets = [a for a in assets if a["asset_class"] == "equity"
                     and not a["components"].get("data_missing")]
    vol_scaled = {a["secid"]: a["components"]["vol_scaled_m3"] for a in equity_assets}
    xsec = strategy.xsec_rank(vol_scaled)
    vols = {a["secid"]: a["components"]["vol_ann"] for a in equity_assets}
    vol_pct = strategy.xsec_rank(vols)

    recommendations: List[Dict] = []
    for asset in assets:
        secid = asset["secid"]
        comp = asset["components"]

        if asset["asset_class"] == "equity" and not comp.get("data_missing"):
            comp["xsec_pct"] = xsec.get(secid)
            comp["tilt"] = strategy.lowvol_div_tilt(vol_pct.get(secid),
                                                    comp.get("div_yield"))
            result = strategy.combine(
                comp, reg, prev_actions.get(secid),
                buy_threshold=cfg["buy_threshold"],
                hold_threshold=cfg["hold_threshold"],
                sentiment_veto_threshold=cfg["sentiment_veto_threshold"])
        elif comp.get("data_missing"):
            result = {"action": "AVOID", "composite": 0.0, "vetoed": False}
        else:
            # Bonds / money market / gold: driven by the allocation cell,
            # own 3m momentum decides BUY vs HOLD
            weight = alloc.get(asset["asset_class"] + "s" if asset["asset_class"] == "bond"
                               else asset["asset_class"], 0)
            m3 = comp.get("m3")
            if weight >= 0.25 and (m3 is None or m3 >= 0):
                result = {"action": "BUY", "composite": round(weight, 4), "vetoed": False}
            else:
                result = {"action": "HOLD", "composite": round(weight, 4), "vetoed": False}

        comp["composite"] = result["composite"]
        comp["vetoed"] = result["vetoed"]

        # 9. Chronos quantile zone for the "forecast vs fact" check next week
        forecast_low = forecast_median = forecast_high = None
        closes = asset.get("closes")
        if closes:
            forecast, _, model_type = predictor.predict(
                [{"close": c} for c in closes], days=7)
            if forecast.get("median"):
                forecast_low = round(forecast["low"][-1], 4)
                forecast_median = round(forecast["median"][-1], 4)
                forecast_high = round(forecast["high"][-1], 4)
                comp["forecast_model"] = model_type

        recommendations.append({
            "secid": secid,
            "asset_class": asset["asset_class"],
            "action": result["action"],
            "components": comp,
            "price_at_reco": asset.get("price"),
            "horizon_days": 7,
            "forecast_low": forecast_low,
            "forecast_median": forecast_median,
            "forecast_high": forecast_high,
        })

    # 10. Persist report + recommendations
    status = "ok"
    if failed:
        status = "partial" if len(failed) <= len(universe) * 0.2 else "failed"
    report_id = await db.save_weekly_report({
        "week_start": week_start,
        "kind": "weekly",
        "created_at": datetime.now().isoformat(),
        "status": status,
        "regime": reg,
        "allocation": alloc,
        "evaluation": evaluation,
    })
    await db.save_recommendations(report_id, recommendations)
    logger.info(f"Weekly report {report_id} saved: {len(recommendations)} recommendations, "
                f"status={status}, failed={failed}")

    return report_id


async def run_midweek_pipeline():
    """Thursday: check the current week's recommendations, raise alarms on
    strong adverse moves. Does not regenerate the plan."""
    cfg = CONFIG["advisor"]
    logger.info("Midweek check started")

    db = Database()
    await db.init_db()
    cache = CacheManager()

    latest = await db.get_latest_weekly_report()
    if not latest:
        logger.info("No weekly report yet, nothing to check")
        return None

    alarms: List[Dict] = []
    interim: List[Dict] = []

    async with MOEXClient(cache_manager=cache, throttle=make_throttle(0.5)) as client:
        for reco in latest["recommendations"]:
            secid = reco["secid"]
            price_at_reco = reco.get("price_at_reco")
            if not price_at_reco:
                continue
            try:
                await sync_candles(client, db, secid)
            except Exception as e:
                logger.error(f"Midweek sync failed for {secid}: {e}")
            latest_close = await db.get_latest_close(secid)
            if not latest_close or not latest_close.get("close"):
                continue
            move = latest_close["close"] / price_at_reco - 1.0
            row = {
                "secid": secid,
                "action": reco["action"],
                "price_at_reco": price_at_reco,
                "price_now": latest_close["close"],
                "interim_return": round(move, 4),
            }
            interim.append(row)
            adverse = (reco["action"] == "BUY" and move < -cfg["alarm_move"]) or \
                      (reco["action"] in ("SELL", "AVOID") and move > cfg["alarm_move"])
            if adverse:
                alarms.append({**row, "reason":
                               f"{reco['action']} ушла против нас на {move:+.1%}"})

    report_id = await db.save_weekly_report({
        "week_start": latest["week_start"],
        "kind": "midweek",
        "created_at": datetime.now().isoformat(),
        "status": "ok",
        "regime": latest.get("regime"),
        "allocation": latest.get("allocation"),
        "evaluation": {"interim": sorted(interim, key=lambda r: r["interim_return"])},
        "alarms": alarms,
    })
    logger.info(f"Midweek report {report_id} saved: {len(alarms)} alarms")

    return report_id
