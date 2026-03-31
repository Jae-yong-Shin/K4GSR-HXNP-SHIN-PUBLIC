#!/usr/bin/env python3
"""
add_front_matter.py - Add YAML front-matter to existing MD files.

Usage:
    python Scripts/add_front_matter.py          # dry-run (show what would be added)
    python Scripts/add_front_matter.py --apply   # actually modify files

This script:
1. Reads each MD file
2. Skips files that already have front-matter
3. Infers title, category, status from path/content
4. Adds front-matter block at the top
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path

DRY_RUN = '--apply' not in sys.argv

# Manual metadata overrides: path -> {title, summary, status, tags}
OVERRIDES = {
    # === architecture ===
    'docs/architecture/AGENT_REFERENCE.md': {
        'title': 'Agent-Document Reference Map',
        'summary': 'Agent별 참조 문서 매핑 (Simulation/Interface/Integration/NLP)',
        'tags': ['agent', 'reference'],
    },
    'docs/architecture/AGENT_ROLES.md': {
        'title': 'Agent Roles (4+1)',
        'summary': 'Simulation/Interface/Integration/NLP 에이전트 역할 정의',
        'tags': ['agent', 'architecture'],
    },
    'docs/architecture/CROSS_PROJECT_RELATIONSHIP.md': {
        'title': 'Cross-Project Relationship',
        'summary': 'Beamline/Ptycho/Tomo 프로젝트 간 관계 및 격리 규칙',
        'tags': ['architecture', 'cross-project'],
    },
    'docs/architecture/DEVELOPMENT_TREE.md': {
        'title': 'Development Tree (DDD Structure)',
        'summary': '프론트엔드 59 JS + 백엔드 Python 서버 전체 구조',
        'tags': ['architecture', 'ddd', 'server'],
    },
    'docs/architecture/GIT_BRANCH_STRATEGY.md': {
        'title': 'Git Branch Strategy',
        'summary': 'master/main/beta/feature 브랜치 역할 및 push 규칙',
        'tags': ['git', 'deployment'],
    },
    'docs/architecture/SERVER_STARTUP_GUIDE.md': {
        'title': 'Server Startup Guide',
        'summary': '서버 5종 시작/종료 절차 및 모드별 구성',
        'tags': ['server', 'startup'],
    },

    # === knowledge ===
    'docs/knowledge/01_project_rules.md': {
        'title': 'Project Rules & Coding Standards',
        'summary': 'ES5 코딩 규칙, CSS 변수, override 패턴, 검증 체크리스트',
        'tags': ['rules', 'coding', 'css'],
    },
    'docs/knowledge/02_physics_overview.md': {
        'title': 'Physics Model Overview',
        'summary': 'MC ray tracer 물리 모델 개요 (소스, DCM, 미러, KB, SSA hybrid)',
        'tags': ['physics', 'mc-engine', 'ray-tracing'],
    },
    'docs/knowledge/03_component_specs.md': {
        'title': 'Component Specs & Debugging Guide',
        'summary': '빔라인 컴포넌트 사양, 광학 레이아웃, PV 명명, 버그 패턴',
        'tags': ['specs', 'components', 'debugging'],
    },
    'docs/knowledge/04_motor_pv_reference.md': {
        'title': 'Motor & PV Reference',
        'summary': 'DEVICE_CONFIGS 기반 모터/PV 전체 목록 및 범위',
        'tags': ['motors', 'epics', 'pv'],
    },
    'docs/knowledge/10_undulator_exact_model.md': {
        'title': 'Undulator Exact Model (Kim 1989)',
        'summary': '언듈레이터 정밀 모델: 에너지-각도 공식, Tanaka-Kitamura 보정',
        'tags': ['physics', 'undulator'],
    },
    'docs/knowledge/11_undulator_2d_spectrum.md': {
        'title': 'Undulator 2D Spectrum',
        'summary': '언듈레이터 2D 에너지-각도 스펙트럼 시각화',
        'tags': ['physics', 'undulator', 'spectrum'],
    },
    'docs/knowledge/12_angular_distribution.md': {
        'title': 'Angular Distribution',
        'summary': '언듈레이터 각도 분포: combined denominator 방식',
        'tags': ['physics', 'undulator'],
    },
    'docs/knowledge/13_beam_hardening.md': {
        'title': 'Beam Hardening & Attenuation',
        'summary': '빔 경화 물리: 질량감쇠계수, 스펙트럼 변화, 감쇠기 모델',
        'tags': ['physics', 'attenuation'],
    },
    'docs/knowledge/14_alignment_physics.md': {
        'title': 'Alignment Physics',
        'summary': 'M1/M2 정렬 물리: half-cut, rocking, rotation center',
        'tags': ['physics', 'alignment', 'mirror'],
    },
    'docs/knowledge/20_profile_2d.md': {
        'title': '2D Beam Profile',
        'summary': '2D 빔 프로파일 렌더링 및 단위 변환',
        'tags': ['ui', 'beam-profile'],
        'status': 'outdated',
    },
    'docs/knowledge/21_profile_1d_units.md': {
        'title': '1D Profile Units',
        'summary': '1D 프로파일 W/mrad^2 -> W/mrad 적분 단위 분석',
        'tags': ['ui', 'units'],
    },
    'docs/knowledge/22_colormap_normalization.md': {
        'title': 'Colormap Normalization',
        'summary': '컬러맵 정규화 버그 수정 및 custom range 방식',
        'tags': ['ui', 'colormap'],
    },
    'docs/knowledge/25_ui_development_guide.md': {
        'title': 'UI Development Guide',
        'summary': 'CSS 변수, 팝업 리사이즈, flex 레이아웃 원칙',
        'tags': ['ui', 'css', 'popup'],
    },
    'docs/knowledge/30_heat_load_guide.md': {
        'title': 'Heat Load Analysis Guide',
        'summary': '열부하 분석: 감쇠기 전후, 흡수 파워, 에너지 보존',
        'tags': ['physics', 'heat-load'],
    },
    'docs/knowledge/31_k4gsr_parameters.md': {
        'title': 'K4GSR Updated Parameters',
        'summary': '저장링 파라미터: emittance 62pm, beta 6.334/2.841, 소스 크기',
        'tags': ['physics', 'parameters', 'electron-beam'],
    },
    'docs/knowledge/40_validation_methods.md': {
        'title': 'Validation Methods',
        'summary': '에너지 보존, 대칭, FWHM 검증 방법론',
        'tags': ['validation', 'testing'],
    },
    'docs/knowledge/41_workflow_guidelines.md': {
        'title': 'Workflow Guidelines',
        'summary': '작업 전 확인, git 사용, 검증 절차 가이드라인',
        'tags': ['workflow', 'guidelines'],
    },
    'docs/knowledge/50_virtual_experiment_architecture.md': {
        'title': 'Virtual Experiment Architecture',
        'summary': '가상 실험 클라이언트-서버 아키텍처 (XAFS/XRD/XRF/Ptycho)',
        'tags': ['experiment', 'architecture', 'server'],
    },
    'docs/knowledge/60_coherence_theory.md': {
        'title': 'Coherence Theory',
        'summary': 'van Cittert-Zernike, Gaussian Schell model, Liouville 정리',
        'tags': ['physics', 'coherence', 'ptychography'],
    },

    # === tasks ===
    'docs/tasks/NEXT_STEPS.md': {
        'title': 'Next Steps',
        'summary': '현재 진행 상황 및 다음 작업 목록',
        'tags': ['progress', 'roadmap'],
    },
    'docs/tasks/BENCHMARK_MC_VS_S4.md': {
        'title': 'MC vs S4 Benchmark',
        'summary': 'MC ray tracer vs Shadow4 FWHM/divergence 비교 분석',
        'tags': ['benchmark', 'mc-engine', 's4'],
    },
    'docs/tasks/TASK_MC_PHYSICS_GOALS.md': {
        'title': 'MC Physics Goals',
        'summary': 'MC 물리 정확도 목표: V-1(<5% S4 편차), M-1(per-ray energy), M-2(4-beam)',
        'tags': ['mc-engine', 'physics', 'goals'],
    },
    'docs/tasks/TASK_EXPERIMENT_SERVER_UI.md': {
        'title': 'Experiment Server UI Task',
        'summary': '가상 실험 서버-UI 통합 (Phase A 완료, B/C 미시작)',
        'tags': ['experiment', 'server', 'ui'],
    },
    'docs/tasks/TASK_MULTILINGUAL_I18N.md': {
        'title': 'Multilingual i18n Task',
        'summary': 'UI 10개 언어 + NLP 35/35 액션 매핑 (2026-03-07 완료)',
        'tags': ['i18n', 'nlp'],
        'status': 'completed',
    },
    'docs/tasks/TASK_NLP_BENCHMARK.md': {
        'title': 'NLP Benchmark Task',
        'summary': 'vLLM Qwen3-32B 97.8% (174/178). 에너지 범위 6건 미해결',
        'tags': ['nlp', 'benchmark', 'vllm'],
    },
    'docs/tasks/SESSION_PTYCHO_WORK.md': {
        'title': 'Ptycho Session Work',
        'summary': '2-pass 합성 데이터 생성, GPU LSQML 엔진 세션 기록',
        'tags': ['ptychography', 'session'],
    },
    'docs/tasks/TASK_PTYCHO_MD_FIRST_SETUP.md': {
        'title': 'Ptycho MD-First Setup',
        'summary': 'K4GSR-PTYCHO 프로젝트 MD-First 워크플로우 설정 지침',
        'tags': ['ptychography', 'workflow'],
    },
    'docs/tasks/TASK_TOMO_MD_FIRST_SETUP.md': {
        'title': 'Tomo MD-First Setup',
        'summary': 'K4GSR-TOMO 프로젝트 MD-First 워크플로우 설정 지침',
        'tags': ['tomography', 'workflow'],
    },

    # === nlp_benchmark ===
    'docs/nlp_benchmark/README.md': {
        'title': 'NLP Benchmark Overview',
        'summary': 'NLP 벤치마크 v2.1 결과 요약 및 디렉토리 가이드',
        'tags': ['nlp', 'benchmark'],
    },
    'docs/nlp_benchmark/BENCHMARK_METHODOLOGY.md': {
        'title': 'Benchmark Methodology',
        'summary': 'v2.0/v2.1 벤치마크 방법론 (154->178 테스트, 28->37 카테고리)',
        'tags': ['nlp', 'benchmark', 'methodology'],
    },
    'docs/nlp_benchmark/COMPARISON.md': {
        'title': 'Model Comparison',
        'summary': 'vLLM/Ollama/Claude/Solar 모델별 성능 비교표',
        'tags': ['nlp', 'benchmark', 'comparison'],
    },
    'docs/nlp_benchmark/EXPERT_FEEDBACK.md': {
        'title': 'Expert Feedback',
        'summary': '전문가 리뷰 2명: 228 vExp 테스트, 10개 우선 패턴',
        'tags': ['nlp', 'feedback', 'expert'],
    },
    'docs/nlp_benchmark/MULTILINGUAL_RESULTS.md': {
        'title': 'Multilingual Results',
        'summary': '다국어 NLP v2: 100% (35/35) 7개 언어',
        'tags': ['nlp', 'multilingual', 'i18n'],
        'status': 'completed',
    },
    'docs/nlp_benchmark/NLP_BENCHMARK_PLAN.md': {
        'title': 'NLP Benchmark Plan',
        'summary': 'v1.0 벤치마크 계획 (v2.1 실적 반영 필요)',
        'tags': ['nlp', 'benchmark', 'plan'],
        'status': 'outdated',
    },

    # === onboarding ===
    'docs/onboarding/SETUP_GUIDE.md': {
        'title': 'Setup Guide',
        'summary': 'Windows/WSL/Mac/Linux 설치 및 초기 설정',
        'tags': ['setup', 'installation'],
    },
    'docs/onboarding/VSCODE_SETUP_GUIDE.md': {
        'title': 'VS Code Setup Guide',
        'summary': 'VS Code + Claude Code 통합 설정, 확장, 단축키',
        'tags': ['vscode', 'setup'],
    },
    'docs/onboarding/BLUESKY_ONBOARDING.md': {
        'title': 'Bluesky Onboarding',
        'summary': 'Bluesky Queue Server 연결, 스캔 플랜 5종 설명',
        'tags': ['bluesky', 'onboarding'],
    },
    'docs/onboarding/EPICS_ONBOARDING.md': {
        'title': 'EPICS Onboarding',
        'summary': 'EPICS Soft IOC 설정, CA Bridge, 86 모터 PV',
        'tags': ['epics', 'onboarding'],
    },

    # === paper ===
    'paper/README.md': {
        'title': 'Paper README',
        'summary': '논문 작업 가이드 (docx canonical, LaTeX legacy)',
        'tags': ['paper'],
    },
    'paper/SESSION_PAPER_WORK.md': {
        'title': 'Paper Session Work',
        'summary': 'v9a 리팩토링 세션 기록: 18개 수정, Virtual Commissioning 프레이밍',
        'tags': ['paper', 'session'],
    },
    'paper/PAPER_LOGIC.md': {
        'title': 'Paper Logic Structure',
        'summary': '논문 v9a 논리 구조: 핵심 주장, 섹션별 분석, 교차 참조',
        'tags': ['paper', 'logic'],
    },
    'paper/LOGIC_FIX_PLAN.md': {
        'title': 'Logic Fix Plan',
        'summary': 'v9a 논리 수정 6+4건 (모두 적용 완료)',
        'tags': ['paper'],
        'status': 'completed',
    },
    'paper/REVIEW_ISSUES.md': {
        'title': 'Review Issues',
        'summary': '16건 리뷰 이슈 (13/16 해결, 3건 잔여)',
        'tags': ['paper', 'review'],
    },
    'paper/revised_paper.md': {
        'title': 'Revised Paper v1 (Legacy)',
        'summary': 'Legacy markdown 버전. docx가 canonical',
        'tags': ['paper'],
        'status': 'archived',
    },
    'paper/revised_paper_v2.md': {
        'title': 'Revised Paper v2 (Legacy)',
        'summary': 'Legacy markdown 버전. docx가 canonical',
        'tags': ['paper'],
        'status': 'archived',
    },
    'paper/supplementary.md': {
        'title': 'Supplementary Material',
        'summary': '보충 자료 S1-S9: 아키텍처, 레이턴시, 검증, NLP',
        'tags': ['paper', 'supplementary'],
    },
    'paper/validation/VERIFICATION_FINDINGS.md': {
        'title': 'Verification Findings',
        'summary': 'MC vs S4 Phase 1-4 검증: 빔 프로파일, 반사율, KB, Fresnel',
        'tags': ['validation', 'mc-engine', 's4'],
    },
    'paper/VERIFICATION_RESULTS.md': {
        'title': 'Verification Results',
        'summary': 'v8->v9a 검증: FWHM 편차 18.6%, hybrid Fresnel 적용',
        'tags': ['validation', 'paper'],
    },

    # === other ===
    'docs/README.md': {
        'title': 'Documentation Directory Guide',
        'summary': 'docs/ 전체 디렉토리 구조 및 파일 안내',
        'tags': ['docs', 'guide'],
    },
    'server/README.md': {
        'title': 'Server README',
        'summary': '백엔드 서버 파일 목록 및 역할 설명',
        'tags': ['server'],
    },
    'server/lora_colab_guide.md': {
        'title': 'LoRA Fine-tuning Guide',
        'summary': 'Qwen3:8b LoRA 학습 가이드 (로컬 GPU / Colab)',
        'tags': ['nlp', 'lora', 'training'],
    },
    'CLAUDE.md': {
        'title': 'CLAUDE.md (Project Instructions)',
        'summary': 'AI Agent 지침: MD-First 워크플로우, 코딩 규칙, 아키텍처',
        'tags': ['agent', 'rules'],
    },
    'README.md': {
        'title': 'Project README',
        'summary': '프로젝트 소개, Quick Start, 아키텍처, 로드맵',
        'tags': ['readme'],
    },

    # === ptycho ===
    'ptycho/CLAUDE.md': {
        'title': 'Ptycho CLAUDE.md',
        'summary': 'K4GSR-PTYCHO AI Agent 지침: 폴더 구조, 코딩 규칙',
        'tags': ['ptychography', 'agent'],
    },
    'ptycho/docs/COHERENCE_MODEL.md': {
        'title': 'Coherence Model',
        'summary': '다중 모드 코히어런스: NanoMAX 기준, van Cittert-Zernike, Hermite',
        'tags': ['ptychography', 'coherence', 'physics'],
    },
    'ptycho/docs/PTYCHO_MIGRATION_TASKS.md': {
        'title': 'Ptycho Migration Tasks',
        'summary': 'K4GSR-PTYCHO <-> Beamline 동기화 작업 목록',
        'tags': ['ptychography', 'migration'],
    },
    'ptycho/docs/TEST_FILES_ARCHIVE.md': {
        'title': 'Ptycho Test Files Archive',
        'summary': '30+ 테스트 스크립트 및 결과 이미지 인벤토리',
        'tags': ['ptychography', 'testing'],
    },
}


def infer_category(filepath):
    """Infer category from file path."""
    fp = filepath.replace('\\', '/')
    if '/architecture/' in fp:
        return 'architecture'
    if '/knowledge/archived/' in fp:
        return 'knowledge'
    if '/knowledge/' in fp:
        return 'knowledge'
    if '/tasks/' in fp:
        return 'tasks'
    if '/nlp_benchmark/' in fp:
        return 'nlp_benchmark'
    if '/onboarding/' in fp:
        return 'onboarding'
    if fp.startswith('paper/') or '/paper/' in fp:
        return 'paper'
    if fp.startswith('ptycho/'):
        return 'other'
    if fp.startswith('server/'):
        return 'other'
    return 'other'


def has_front_matter(filepath):
    """Check if file already has YAML front-matter."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            return first_line == '---'
    except Exception:
        return False


def get_title_from_content(filepath):
    """Extract first heading as title."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('# '):
                    return line.lstrip('# ').strip()
    except Exception:
        pass
    return Path(filepath).stem


def get_file_date(filepath):
    """Get file modification date."""
    try:
        ts = os.path.getmtime(filepath)
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d')


def build_front_matter(rel_path, abs_path):
    """Build front-matter string for a file."""
    override = OVERRIDES.get(rel_path, {})

    title = override.get('title', get_title_from_content(abs_path))
    category = override.get('category', infer_category(rel_path))
    status = override.get('status', 'archived' if '/archived/' in rel_path else 'current')
    tags = override.get('tags', [])
    summary = override.get('summary', '')
    updated = get_file_date(abs_path)

    tags_str = '[' + ', '.join(tags) + ']' if tags else '[]'

    fm = '---\n'
    fm += 'title: "' + title + '"\n'
    fm += 'category: ' + category + '\n'
    fm += 'status: ' + status + '\n'
    fm += 'updated: ' + updated + '\n'
    fm += 'tags: ' + tags_str + '\n'
    fm += 'summary: "' + summary + '"\n'
    fm += '---\n'
    return fm


def collect_all_md(base_dir):
    """Collect all MD files to process."""
    files = []
    scan_dirs = ['docs', 'paper', 'server', 'ptycho/docs', 'validation']

    for sd in scan_dirs:
        full = os.path.join(base_dir, sd)
        if not os.path.isdir(full):
            continue
        for root, dirs, fnames in os.walk(full):
            dirs[:] = [d for d in dirs if d not in
                       ('__pycache__', '.venv', 'node_modules', '.git')]
            for fn in fnames:
                if fn.endswith('.md'):
                    fp = os.path.join(root, fn)
                    rel = os.path.relpath(fp, base_dir).replace('\\', '/')
                    files.append((rel, fp))

    # Special root-level and ptycho/CLAUDE.md
    for rf in ['CLAUDE.md', 'README.md', 'ptycho/CLAUDE.md']:
        fp = os.path.join(base_dir, rf)
        if os.path.isfile(fp):
            files.append((rf, fp))

    return files


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = collect_all_md(base_dir)

    added = 0
    skipped = 0

    for rel, abs_path in sorted(files):
        if has_front_matter(abs_path):
            skipped += 1
            continue

        fm = build_front_matter(rel, abs_path)

        if DRY_RUN:
            print('[DRY] ' + rel)
        else:
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                with open(abs_path, 'w', encoding='utf-8') as f:
                    f.write(fm + content)
                print('[ADD] ' + rel)
            except Exception as e:
                print('[ERR] ' + rel + ': ' + str(e))
                continue
        added += 1

    mode = 'DRY RUN' if DRY_RUN else 'APPLIED'
    print('\n' + mode + ': ' + str(added) + ' files updated, ' + str(skipped) + ' already had front-matter')

    if DRY_RUN:
        print('\nRun with --apply to actually modify files.')


if __name__ == '__main__':
    main()
