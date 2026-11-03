package sparse_memory_pkg;
    class memory_page;
        // Two-state bytes, allocated only on write; never a 1 GiB four-state array.
        byte unsigned data[4096];
    endclass

    class sparse_memory;
        memory_page pages[longint unsigned];
        longint unsigned base_addr, limit_addr;
        function new(longint unsigned base_addr, longint unsigned size_bytes);
            this.base_addr = base_addr;
            this.limit_addr = base_addr + size_bytes;
        endfunction
        function bit in_range(longint unsigned addr, longint unsigned size_bytes=1);
            return addr >= base_addr && addr <= limit_addr && size_bytes <= limit_addr-addr;
        endfunction
        function byte unsigned read_byte(longint unsigned addr);
            if (!in_range(addr)) $fatal(1, "MEM_RANGE read %h", addr);
            if (!pages.exists(addr >> 12)) return 0;
            return pages[addr >> 12].data[addr & 4095];
        endfunction
        function void write_byte(longint unsigned addr, byte unsigned value);
            if (!in_range(addr)) $fatal(1, "MEM_RANGE write %h", addr);
            if (!pages.exists(addr >> 12)) pages[addr >> 12] = new;
            pages[addr >> 12].data[addr & 4095] = value;
        endfunction
        function void zero_range(longint unsigned addr, longint unsigned size_bytes);
            longint unsigned lo, hi;
            if (!in_range(addr, size_bytes)) $fatal(1, "MEM_RANGE zero");
            // Unallocated BSS is already zero. Work scales with allocated pages.
            foreach (pages[p]) begin
                lo = (p << 12) > addr ? (p << 12) : addr;
                hi = ((p+1) << 12) < addr+size_bytes ? ((p+1) << 12) : addr+size_bytes;
                for (longint unsigned a=lo; a<hi; a++) pages[p].data[a & 4095] = 0;
            end
        endfunction
        task load_bin(string filename, longint unsigned addr, longint unsigned size_bytes);
            integer fd, count, want;
            longint unsigned done_bytes;
            byte unsigned buffer[4096];
            if (!in_range(addr, size_bytes)) $fatal(1, "MEM_RANGE image");
            fd = $fopen(filename, "rb");
            if (!fd) $fatal(1, "MEM_IMAGE cannot open %s", filename);
            if ($fseek(fd, 0, 2) != 0 || $ftell(fd) != size_bytes)
                $fatal(1, "MEM_IMAGE size mismatch %s", filename);
            if ($fseek(fd, 0, 0) != 0) $fatal(1, "MEM_IMAGE seek");
            done_bytes = 0;
            while (done_bytes < size_bytes) begin
                want = size_bytes-done_bytes > 4096 ? 4096 : size_bytes-done_bytes;
                count = $fread(buffer, fd, 0, want);
                if (count != want) $fatal(1, "MEM_IMAGE short read");
                for (int i=0; i<count; i++) write_byte(addr+done_bytes+i, buffer[i]);
                done_bytes += count;
            end
            $fclose(fd);
        endtask
        task load_plan(string filename, string mode);
            integer fd, rc;
            string line, op, path;
            longint unsigned addr, size_bytes;
            if (mode != "PRELOAD" && mode != "PROTOCOL_BOOT") $fatal(1, "MEM_MODE invalid");
            if (filename == "") return;
            if (mode == "PROTOCOL_BOOT") $fatal(1, "MEM_PRELOAD_FORBIDDEN");
            fd = $fopen(filename, "r");
            if (!fd) $fatal(1, "MEM_IMAGE cannot open plan");
            while ($fgets(line, fd)) begin
                rc = $sscanf(line, "%s %h %h %s", op, addr, size_bytes, path);
                if (rc == 4 && op == "B") load_bin(path, addr, size_bytes);
                else if (rc == 3 && op == "Z") zero_range(addr, size_bytes);
                else $fatal(1, "MEM_IMAGE invalid plan line");
            end
            $fclose(fd);
        endtask
    endclass
endpackage
