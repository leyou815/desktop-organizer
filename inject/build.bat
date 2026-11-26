@echo off
rem ============================================================
rem  重新编译注入组件，并把产物放到 tap\ 供打包/安装使用
rem  需要 Rust（rustup）；没有 Rust 的话不用跑这个 —— 仓库里
rem  已经带了编好的 tap\do_inject.dll
rem ============================================================
setlocal
cd /d "%~dp0"
cargo build --release || goto :err
copy /y "target\release\do_inject.dll" "..\tap\do_inject.dll" || goto :err
echo OK: tap\do_inject.dll
goto :end
:err
echo build failed
exit /b 1
:end
endlocal
