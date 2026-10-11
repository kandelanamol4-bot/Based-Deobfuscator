local OPCODES = {[0]=function(a,b) return a+b end}; local bytecode = {0,1,2}; local vm=function(pc) while true do local op=bytecode[pc] OPCODES[op]() end end
