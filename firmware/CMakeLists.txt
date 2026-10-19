#
# Copyright (c) 2026 Conexio Technologies, Inc
#
# SPDX-License-Identifier: Apache-2.0
#

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(nrplus_exp_store)

target_sources(app PRIVATE
  src/main.c
  src/sf_codec.c
  src/sf_dedup.c
  src/sf_store.c
  src/sf_link.c
  src/sf_node.c
  src/sf_port.c
  src/sf_shell.c
  src/sf_persist.c
)

target_include_directories(app PRIVATE src)

# Git revision of the firmware sources, logged at every boot (BOOT_INFO). "-dirty" means uncommitted
# changes under firmware/. It is read when CMake configures, so use a fresh build directory after a commit.
execute_process(COMMAND git -C ${CMAKE_CURRENT_SOURCE_DIR} rev-parse --short=8 HEAD
		OUTPUT_VARIABLE SF_GIT_REV OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
execute_process(COMMAND git -C ${CMAKE_CURRENT_SOURCE_DIR} status --porcelain -- .
		OUTPUT_VARIABLE SF_GIT_DIRTY OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
if(NOT SF_GIT_REV)
  set(SF_GIT_REV "unknown")
elseif(SF_GIT_DIRTY)
  set(SF_GIT_REV "${SF_GIT_REV}-dirty")
endif()
target_compile_definitions(app PRIVATE SF_GIT_REV=\"${SF_GIT_REV}\")
