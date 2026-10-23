using System.Buffers.Binary;
using System.Text;

namespace SphinxInstaller;

// ---------- минимальный NBT (хватает для servers.dat) ----------
public sealed class NbtTag
{
    public byte Type;
    public object Value;
    public NbtTag(byte type, object value) { Type = type; Value = value; }
}

public sealed class NbtList
{
    public byte ElemType = 10;
    public List<object> Items = new();
}

public sealed class Compound
{
    public readonly List<(string Name, NbtTag Tag)> Items = new();

    public NbtTag Get(string name)
    {
        foreach (var i in Items) if (i.Name == name) return i.Tag;
        return null;
    }

    public void Set(string name, NbtTag tag)
    {
        for (int i = 0; i < Items.Count; i++)
            if (Items[i].Name == name) { Items[i] = (name, tag); return; }
        Items.Add((name, tag));
    }
}

public sealed class NbtReader
{
    readonly byte[] b;
    int p;
    public NbtReader(byte[] data, int pos) { b = data; p = pos; }

    short I16() { var v = BinaryPrimitives.ReadInt16BigEndian(b.AsSpan(p)); p += 2; return v; }
    ushort U16() { var v = BinaryPrimitives.ReadUInt16BigEndian(b.AsSpan(p)); p += 2; return v; }
    int I32() { var v = BinaryPrimitives.ReadInt32BigEndian(b.AsSpan(p)); p += 4; return v; }
    long I64() { var v = BinaryPrimitives.ReadInt64BigEndian(b.AsSpan(p)); p += 8; return v; }
    string Str() { int n = U16(); var s = Encoding.UTF8.GetString(b, p, n); p += n; return s; }

    public object Read(byte t)
    {
        switch (t)
        {
            case 1: return (sbyte)b[p++];
            case 2: return I16();
            case 3: return I32();
            case 4: return I64();
            case 5: { var v = BinaryPrimitives.ReadSingleBigEndian(b.AsSpan(p)); p += 4; return v; }
            case 6: { var v = BinaryPrimitives.ReadDoubleBigEndian(b.AsSpan(p)); p += 8; return v; }
            case 7: { int n = I32(); var a = new byte[n]; Array.Copy(b, p, a, 0, n); p += n; return a; }
            case 8: return Str();
            case 9:
            {
                byte et = b[p++];
                int n = I32();
                var l = new NbtList { ElemType = et };
                for (int i = 0; i < n; i++) l.Items.Add(Read(et));
                return l;
            }
            case 10:
            {
                var c = new Compound();
                while (b[p] != 0)
                {
                    byte nt = b[p++];
                    string name = Str();
                    c.Items.Add((name, new NbtTag(nt, Read(nt))));
                }
                p++;
                return c;
            }
            case 11: { int n = I32(); var a = new int[n]; for (int i = 0; i < n; i++) a[i] = I32(); return a; }
            case 12: { int n = I32(); var a = new long[n]; for (int i = 0; i < n; i++) a[i] = I64(); return a; }
            default: throw new InvalidDataException("bad nbt tag " + t);
        }
    }
}

public static class NbtWriter
{
    static void W16(Stream s, short v) { Span<byte> x = stackalloc byte[2]; BinaryPrimitives.WriteInt16BigEndian(x, v); s.Write(x); }
    static void WU16(Stream s, ushort v) { Span<byte> x = stackalloc byte[2]; BinaryPrimitives.WriteUInt16BigEndian(x, v); s.Write(x); }
    static void W32(Stream s, int v) { Span<byte> x = stackalloc byte[4]; BinaryPrimitives.WriteInt32BigEndian(x, v); s.Write(x); }
    static void W64(Stream s, long v) { Span<byte> x = stackalloc byte[8]; BinaryPrimitives.WriteInt64BigEndian(x, v); s.Write(x); }
    static void WStr(Stream s, string v) { var bytes = Encoding.UTF8.GetBytes(v); WU16(s, (ushort)bytes.Length); s.Write(bytes); }

    public static void Write(Stream s, byte t, object v)
    {
        switch (t)
        {
            case 1: s.WriteByte((byte)(sbyte)v); break;
            case 2: W16(s, (short)v); break;
            case 3: W32(s, (int)v); break;
            case 4: W64(s, (long)v); break;
            case 5: { Span<byte> x = stackalloc byte[4]; BinaryPrimitives.WriteSingleBigEndian(x, (float)v); s.Write(x); break; }
            case 6: { Span<byte> x = stackalloc byte[8]; BinaryPrimitives.WriteDoubleBigEndian(x, (double)v); s.Write(x); break; }
            case 7: { var a = (byte[])v; W32(s, a.Length); s.Write(a); break; }
            case 8: WStr(s, (string)v); break;
            case 9:
            {
                var l = (NbtList)v;
                s.WriteByte(l.ElemType);
                W32(s, l.Items.Count);
                foreach (var i in l.Items) Write(s, l.ElemType, i);
                break;
            }
            case 10:
            {
                var c = (Compound)v;
                foreach (var (name, tag) in c.Items)
                {
                    s.WriteByte(tag.Type);
                    WStr(s, name);
                    Write(s, tag.Type, tag.Value);
                }
                s.WriteByte(0);
                break;
            }
            case 11: { var a = (int[])v; W32(s, a.Length); foreach (var i in a) W32(s, i); break; }
            case 12: { var a = (long[])v; W32(s, a.Length); foreach (var i in a) W64(s, i); break; }
            default: throw new InvalidDataException("bad nbt tag " + t);
        }
    }
}

public static class Servers
{
    /// <summary>Добавляет сервер в servers.dat. false — если такой уже есть.</summary>
    public static bool Add(string gameDir, string name, string ip)
    {
        var path = Path.Combine(gameDir, "servers.dat");
        Directory.CreateDirectory(gameDir);
        var root = new Compound();

        if (File.Exists(path))
        {
            var data = File.ReadAllBytes(path);
            if (data.Length > 0)
            {
                File.Copy(path, path + ".bak", true);
                int nameLen = BinaryPrimitives.ReadUInt16BigEndian(data.AsSpan(1));
                root = (Compound)new NbtReader(data, 3 + nameLen).Read(10);
            }
        }

        NbtList list;
        if (root.Get("servers")?.Value is NbtList existing && (existing.Items.Count == 0 || existing.ElemType == 10))
            list = existing;
        else
            list = new NbtList();

        foreach (var item in list.Items)
        {
            if (item is Compound c && c.Get("ip")?.Value is string sip &&
                sip.Equals(ip, StringComparison.OrdinalIgnoreCase))
                return false;
        }

        var srv = new Compound();
        srv.Set("name", new NbtTag(8, name));
        srv.Set("ip", new NbtTag(8, ip));
        list.Items.Add(srv);
        list.ElemType = 10;
        root.Set("servers", new NbtTag(9, list));

        using var ms = new MemoryStream();
        ms.Write(new byte[] { 0x0A, 0x00, 0x00 });
        NbtWriter.Write(ms, 10, root);
        File.WriteAllBytes(path, ms.ToArray());
        return true;
    }
}
