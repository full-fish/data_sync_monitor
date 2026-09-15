#!/usr/bin/env python3
"""
코레일(KTX) 예매 자동 재시도 스크립트 (pykorail 기반).

지정한 구간/날짜/시간대의 열차를 주기적으로 검색해서,
자리가 나는 순간(취소표 포함) 자동으로 예매(결제 전 단계까지)를 시도합니다.

사용법:
    KORAIL_ID=내아이디 KORAIL_PW=비밀번호 python3 korail_reserve.py

필요 패키지 (Python 3.10 이상 필요):
    pip install pykorail

주의:
- 코레일 이용약관은 매크로/자동화 프로그램을 통한 예매를 금지하고 있습니다.
  개인 여정을 위한 용도라도 계정 이용 제한 등 리스크가 있을 수 있으니
  참고하시고, 서버 부담을 줄이기 위해 요청 간격(--interval)을 너무
  짧게 두지 마세요.
- 결제(카드 정보 입력)는 이 스크립트가 하지 않습니다. 예약에 성공하면
  알림을 드리니, 코레일 앱/사이트에서 직접 결제를 완료하세요
  (예약 유지시간이 짧으니 알림 뜨면 바로 결제하세요).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from pykorail import (
        AdultPassenger,
        Korail,
        KorailError,
        NeedToLoginError,
        NetFunnelError,
        NoResultsError,
        PastDepartureError,
        SoldOutError,
        TransportError,
    )
    from pykorail.device import profile_by_id, random_profile
    from pykorail.options import ReserveOption, TrainType
except ImportError:
    print(
        "pykorail 패키지가 필요합니다 (Python 3.10+): pip install pykorail",
        file=sys.stderr,
    )
    raise

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("korail_reserve")

DEVICE_ID_FILE = Path(__file__).with_name(".korail_device_id")


@dataclass
class Config:
    dep: str
    arr: str
    date: str  # yyyyMMdd
    start_hhmm: str  # hhmm, 검색 시작 시각
    end_hhmm: str  # hhmm, 이 시각 이전 출발 열차만 예매 시도
    interval_sec: float
    train_type: str
    adults: int
    include_waiting_list: bool
    test: bool


def notify(title: str, message: str) -> None:
    """맥에서 소리+알림으로 예매 성공을 바로 알아챌 수 있게 함."""
    if sys.platform == "darwin":
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{message}" with title "{title}" sound name "Glass"',
                ],
                check=False,
            )
        except Exception:
            pass
    log.info("%s: %s", title, message)


def load_device_profile():
    """이전 실행에서 저장한 기기 프로파일을 재사용 (없으면 새로 뽑아 저장).

    매 실행마다 다른 기기로 보이는 것보다, 하나의 프로파일을 계속 쓰는 편이
    자연스럽다고 pykorail 문서가 권장합니다.
    """
    saved_id = None
    if DEVICE_ID_FILE.exists():
        try:
            saved_id = json.loads(DEVICE_ID_FILE.read_text()).get("id")
        except Exception:
            saved_id = None

    profile = (profile_by_id(saved_id) if saved_id else None) or random_profile()
    DEVICE_ID_FILE.write_text(json.dumps({"id": profile.id}))
    return profile


def safe_relogin(korail: Korail, korail_id: str, korail_pw: str) -> None:
    """재로그인 자체가 네트워크 오류로 실패해도 죽지 않게 감싼 버전."""
    try:
        korail.login(korail_id, korail_pw)
    except Exception as e:
        log.warning("재로그인 실패, 다음 루프에서 다시 시도: %s: %s", type(e).__name__, e)


def login_with_retry(korail_id: str, korail_pw: str, device_profile, tries: int = 5) -> Korail:
    """시작 시 네트워크가 잠깐 불안정해도 몇 번 더 시도해본다."""
    for i in range(1, tries + 1):
        try:
            return Korail.logged_in(korail_id, korail_pw, device_profile=device_profile)
        except Exception as e:
            if i == tries:
                raise
            log.warning("로그인 실패(%d/%d), 5초 후 재시도: %s: %s", i, tries, type(e).__name__, e)
            time.sleep(5)
    raise AssertionError("unreachable")


def candidate_trains(korail: Korail, cfg: Config, depart_after: datetime):
    """검색 결과 중 지정한 시간대(start~end) 안에 출발하는 열차만 반환."""
    trains = korail.trains.search(
        cfg.dep,
        cfg.arr,
        depart_after=depart_after,
        train_type=cfg.train_type,
        include_waiting_list=cfg.include_waiting_list,
    )
    end_hhmmss = cfg.end_hhmm + "00"
    return [t for t in trains if t.dep_time <= end_hhmmss]


def run(cfg: Config) -> None:
    korail_id = os.environ.get("KORAIL_ID")
    korail_pw = os.environ.get("KORAIL_PW")
    if not korail_id or not korail_pw:
        log.error("환경변수 KORAIL_ID / KORAIL_PW 를 설정해주세요.")
        sys.exit(1)

    device_profile = load_device_profile()
    depart_after = datetime.strptime(cfg.date + cfg.start_hhmm, "%Y%m%d%H%M")

    korail = login_with_retry(korail_id, korail_pw, device_profile)
    log.info("로그인 성공 (%s)", korail.name or korail.membership_number)

    if cfg.test:
        try:
            trains = candidate_trains(korail, cfg, depart_after)
            log.info("검색 성공, %d개 열차 발견 (좌석 있는 것만):", len(trains))
            for t in trains:
                log.info("  - %s", t)
        except NoResultsError:
            log.info("검색 성공, 해당 시간대에 좌석 있는 열차는 없음 (연결 자체는 정상)")
        except PastDepartureError as e:
            log.info("검색 시각이 과거라 검색은 스킵됐지만, 로그인은 정상 동작함: %s", e)
        korail.close()
        return

    passengers = [AdultPassenger(cfg.adults)]
    attempt = 0

    try:
        while True:
            attempt += 1
            try:
                trains = candidate_trains(korail, cfg, depart_after)
            except NoResultsError:
                trains = []
            except PastDepartureError:
                log.error("검색 시작 시각이 이미 지났습니다. 종료합니다.")
                return
            except NeedToLoginError:
                log.warning("세션 만료, 재로그인 시도")
                safe_relogin(korail, korail_id, korail_pw)
                continue
            except (NetFunnelError, TransportError) as e:
                log.warning("[%d회] 네트워크/대기열 오류: %s", attempt, e)
                trains = []
            except KorailError as e:
                log.warning("[%d회] 검색 중 오류: %s", attempt, e)
                trains = []
            except Exception as e:
                # curl_cffi/requests 쪽 타임아웃·연결 끊김 등은 pykorail이 감싸주지
                # 않고 그대로 올라온다. 며칠씩 무인으로 돌리는 스크립트라 여기서
                # 죽으면 안 되니 무엇이 됐든 로그만 남기고 계속 돈다.
                log.warning("[%d회] 예상치 못한 오류(검색): %s: %s", attempt, type(e).__name__, e)
                trains = []

            if not trains:
                log.info(
                    "[%d회] %s~%s 사이 출발 열차 없음, %.1f초 후 재시도",
                    attempt,
                    cfg.start_hhmm,
                    cfg.end_hhmm,
                    cfg.interval_sec,
                )
            else:
                for train in trains:
                    try:
                        log.info("[%d회] 예약 시도: %s", attempt, train)
                        reservation = korail.reservations.create(
                            train,
                            passengers=passengers,
                            option=ReserveOption.GENERAL_FIRST,
                        )
                        notify(
                            "예매 성공! 코레일 앱에서 바로 결제하세요",
                            f"{cfg.dep} -> {cfg.arr} {train}",
                        )
                        log.info("예약 완료 (결제 대기): %s", reservation)
                        return
                    except SoldOutError:
                        log.info("[%d회] 매진: %s", attempt, train)
                        continue
                    except NeedToLoginError:
                        log.warning("세션 만료, 재로그인 시도")
                        safe_relogin(korail, korail_id, korail_pw)
                        break
                    except KorailError as e:
                        log.warning("[%d회] 예약 중 오류(%s): %s", attempt, train, e)
                        continue
                    except Exception as e:
                        log.warning(
                            "[%d회] 예상치 못한 오류(예약, %s): %s: %s",
                            attempt,
                            train,
                            type(e).__name__,
                            e,
                        )
                        continue

            sleep_for = cfg.interval_sec + random.uniform(0, cfg.interval_sec * 0.5)
            time.sleep(sleep_for)
    finally:
        korail.close()


def parse_args() -> Config:
    p = argparse.ArgumentParser(description="코레일 예매 자동 재시도")
    p.add_argument("--dep", default="광명")
    p.add_argument("--arr", default="대전")
    p.add_argument(
        "--date",
        default="20260925",
        help="yyyyMMdd, 기본값 2026-09-25(추석 연휴)",
    )
    p.add_argument("--start-time", default="0900", help="hhmm, 검색 시작 시각")
    p.add_argument("--end-time", default="1000", help="hhmm, 이 시각 이전 출발만 시도")
    p.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="재시도 간격(초). 너무 짧게 두지 마세요.",
    )
    p.add_argument("--adults", type=int, default=1)
    p.add_argument(
        "--train-type",
        default=TrainType.KTX,
        help="기본값 KTX. 전체 열차종은 TrainType.ALL",
    )
    p.add_argument(
        "--include-waiting-list",
        action="store_true",
        help="좌석이 없어도 예약대기가 열려있으면 함께 시도",
    )
    p.add_argument(
        "--test",
        action="store_true",
        help="로그인 + 검색 1회만 해보고 종료 (예약 시도 안 함, 연결 확인용)",
    )
    args = p.parse_args()
    return Config(
        dep=args.dep,
        arr=args.arr,
        date=args.date,
        start_hhmm=args.start_time,
        end_hhmm=args.end_time,
        interval_sec=args.interval,
        train_type=args.train_type,
        adults=args.adults,
        include_waiting_list=args.include_waiting_list,
        test=args.test,
    )


if __name__ == "__main__":
    cfg = parse_args()
    log.info(
        "%s -> %s, %s %s~%s 사이 열차 예매 재시도 시작",
        cfg.dep,
        cfg.arr,
        cfg.date,
        cfg.start_hhmm,
        cfg.end_hhmm,
    )
    try:
        run(cfg)
    except KeyboardInterrupt:
        log.info("사용자에 의해 중단됨")
