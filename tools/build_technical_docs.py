"""Build source-bound project documentation and independently verify its formulas.

Writes only docs/technical, validation/documentation.json and temporary previews.
Never fits, rebuilds, exports or replaces a formal CAD model.
"""
import argparse
import base64
import copy
import datetime
import hashlib
import html
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT/'docs/technical'
sys.path.insert(0, str(ROOT))
sys.path.append(str(ROOT/'.vendor'))
sys.path.append(str(ROOT/'.devtools'))
SOURCES = {}
CHAPTERS = ['01_PROJECT.md', '02_FITTING.md', '03_MATHEMATICS.md',
            '04_REPRODUCTION.md', '05_INNER_CONTROLS.md']
CANDIDATE_LABELS = {'previous': '七次 Bézier 基准', 'bezier7': '优化七次 Bézier',
                    'quintic_C3': '五次 C3 B 样条', 'bezier9': '九次 Bézier'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source(path):
    path = ROOT/path
    SOURCES[path.relative_to(ROOT).as_posix()] = digest(path)
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def block(filename, name, content):
    path = DOC/filename
    text = path.read_text(encoding='utf-8')
    pattern = rf'<!-- BEGIN {name} -->.*?<!-- END {name} -->'
    replacement = f'<!-- BEGIN {name} -->\n{content.strip()}\n<!-- END {name} -->'
    text, count = re.subn(pattern, lambda m: replacement, text, flags=re.S)
    if count != 1:
        raise ValueError(f'Expected one generated block: {filename} {name}')
    path.write_text(text, encoding='utf-8')


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(str(v) for v in row)+' |' for row in rows])


def load_reproducer():
    spec = importlib.util.spec_from_file_location('documented_profiles', DOC/'reproduce_profiles.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def find_quarter(packet, inner):
    matches = []
    for index, face in enumerate(packet['bodies'][0]['faces']):
        support = face['surface']
        if support['type'] != 'SurfaceOfLinearExtrusion':
            continue
        definition = support.get('basis', {}).get('original', {})
        poles = definition.get('poles', [])
        if (definition.get('degree') == 7 and poles
                and (len(poles) > 8) == inner and min(min(p[:2]) for p in poles) > 0):
            matches.append((index, definition))
    if len(matches) != 1:
        raise ValueError(f'Expected one positive quadrant support: {len(matches)}')
    return matches[0]


def collect_data():
    manifest = source('exact_delivery_manifest.json')
    acceptance = source('exact_release_check.json')
    if not manifest['complete'] or not acceptance['complete']:
        raise ValueError('Document a completed accepted release only')
    profiles = source('data/fitted_profiles.json')['profiles']
    data = {'schema': 'documented-exact-profiles-v1', 'units': 'mm', 'release': manifest['release'],
            'scope': 'Exact frozen outer and inner profiles; analytic design parameters for regular features',
            'numeric_convention': 'Round-trip decimal representations of published IEEE 754 binary64 values',
            'full_outline': 'Cq(t)=R^q C(t); Lq(t)=(1-t) R^q C(1)+t R^(q+1) C(0); R(x,y)=(y,-x)',
            'profiles': {}}
    reports = {}; candidates = {}; heights = {}; parameters = {}; audits = {}; offsets = {}
    for name, profile in profiles.items():
        definition = {k: copy.deepcopy(profile[k]) for k in ('degree', 'controls_mm', 'weights')}
        definition.update(knots=[0.0, 1.0], multiplicities=[8, 8], domain=[0.0, 1.0], periodic=False)
        data['profiles'][name] = {'outer': definition, 'nominal_width_mm': profile['width_mm'],
                                 'nominal_xy_scale': profile['xy_scale'], 'inner': {}}
        for thickness in (2, 3):
            row = next(r for r in manifest['models'] if r['model'] == name and r['family'] == 'curve'
                       and r['variant'] == f'{thickness}mm')
            packet = source(row['canonical']['file'])
            index, original = find_quarter(packet, True)
            inner = {k: copy.deepcopy(original[k]) for k in ('degree', 'weights', 'knots', 'multiplicities', 'domain', 'periodic')}
            inner['controls_mm'] = [p[:2] for p in original['poles']]
            inner['source'] = {'canonical_file': row['canonical']['file'], 'canonical_sha256': row['canonical']['sha256'],
                               'body': 0, 'face': index, 'brep': row['files']['.brep']['file']}
            data['profiles'][name]['inner'][str(thickness)] = inner
            folder = f'results/masters/{name}/enclosure-{thickness}mm'
            parameters[name, thickness] = source(folder+'/model_parameters.json')
            current = source(folder+'/validation.json')
            offsets[name, thickness] = current['inner_profile_offset']
            audits[name, thickness] = {
                'base': source(folder+'/base_geometry_audit.json'),
                'features': source(folder+('/mini_opening_interface_audit.json' if name == 'mac-mini' else '/studio_final_audit.json'))}
        data['profiles'][name]['base'] = parameters[name, 2]['base_design']
        reports[name] = source(f'results/fitting/reference/{name}/optimized_report.json')
        candidates[name] = source(f'results/fitting/reference/{name}/model_comparison.json')
        heights[name] = source(f'results/fitting/reference/{name}/height_dependence.json')
    pattern = source('results/masters/mac-mini/enclosure-2mm/uniform_vent_pattern.json')
    data['mini_vents'] = {k: pattern[k] for k in ('phase_radians', 'angular_pitch_radians', 'width_mm', 'length_mm', 'center_z_mm')}
    data['studio_rear_grid'] = parameters['mac-studio', 2]['rear_grid_design']
    for name in ('data/enclosure_design.json', 'configs/models.json', 'configs/protocol.json',
                 'exact_migration_status.json', 'fit_reference_manifest.json'):
        source(name)
    data['source_bindings'] = [{'file': p, 'sha256': h} for p, h in sorted(SOURCES.items())]
    save(DOC/'geometry_definition.json', data)
    return data, manifest, reports, candidates, heights, parameters, audits, offsets


def verify_formulas(data, manifest, temporary):
    import numpy as np
    from scipy.interpolate import BSpline
    import cadquery as cq
    import rhino3dm as r
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    reproduced = load_reproducer(); results = []
    temporary.mkdir(parents=True, exist_ok=True)
    for name, profile in data['profiles'].items():
        doc = r.File3dm(); doc.Settings.ModelUnitSystem = r.UnitSystem.Millimeters
        for wall in (None, 2, 3):
            definition = profile['outer'] if wall is None else profile['inner'][str(wall)]
            evaluate = reproduced.quarter(profile, wall)
            scipy = BSpline(reproduced.expand_knots(definition), definition['controls_mm'], definition['degree'])
            parameters = np.linspace(0, 1, 2001)
            error = float(np.max(np.abs(np.array([evaluate(float(t)) for t in parameters])-scipy(parameters))))
            if error > 1e-10:
                raise ValueError('Independent formula differs from spline evaluation')
            variant = '2mm' if wall is None else f'{wall}mm'
            row = next(m for m in manifest['models'] if m['model'] == name and m['family'] == 'curve' and m['variant'] == variant)
            shape = cq.Shape.importBrep(str(ROOT/row['files']['.brep']['file']))
            actual = None
            for face in shape.Faces():
                if face.geomType() != 'EXTRUSION':continue
                curve = BRepAdaptor_Surface(face.wrapped).BasisCurve()
                if curve.Degree() != 7 or (curve.NbPoles() > 8) != (wall is not None):continue
                p0, p1 = curve.Value(0), curve.Value(1)
                if min(p0.X(),p0.Y(),p1.X(),p1.Y()) > 0:
                    actual = curve; break
            if actual is None:raise ValueError('Cannot find actual BREP support')
            occt_error = 0.0
            for t in np.linspace(0, 1, 257):
                p = actual.Value(float(t)); expected = evaluate(float(t))
                occt_error = max(occt_error, math.hypot(p.X()-expected[0],p.Y()-expected[1]))
            if occt_error > 1e-10:raise ValueError('Formula differs from actual BREP support')
            outline = reproduced.rhino_outline(profile, wall); doc.Objects.AddCurve(outline)
            closure = math.dist(reproduced.point(profile,0,wall), reproduced.point(profile,8,wall))
            k, ks, speed = geometry(scipy, np.array([0.,1.]))
            poles=np.asarray(definition['controls_mm'])
            symmetry=float(np.max(np.abs(poles-poles[::-1,::-1])))
            if closure>1e-12 or max(abs(k))>1e-8 or max(abs(ks))>1e-8 or min(speed)<=0 or symmetry>1e-10:
                raise ValueError('Formula fails closure, endpoint G3, regularity or symmetry')
            if wall is None and (np.ptp(poles[:4,1])!=0 or np.ptp(poles[-4:,0])!=0):
                raise ValueError('Outer controls do not establish the stated G3 proof')
            results.append({'model':name,'curve':'outer' if wall is None else f'inner_{wall}mm',
                            'scipy_max_coordinate_error_mm':error,'actual_brep_max_point_error_mm':occt_error,
                            'closed_point_error_mm':closure,'endpoint_curvature_max_per_mm':float(max(abs(k))),
                            'endpoint_curvature_derivative_max_per_mm2':float(max(abs(ks))),
                            'endpoint_minimum_speed':float(min(speed)),
                            'control_diagonal_symmetry_error_mm':symmetry,'passed':True})
        path = temporary/f'{name}_exact_formula_check.3dm'
        if not doc.Write(str(path),8):raise IOError('Formula 3DM write failed')
        reopened = r.File3dm.Read(str(path))
        if reopened.Settings.ModelUnitSystem != r.UnitSystem.Millimeters or len(reopened.Objects)!=3:
            raise ValueError('Formula readback units or object count differs')
        for index,wall in enumerate((None,2,3)):
            curve = reopened.Objects[index].Geometry
            if not (curve.IsClosed and curve.IsValid and curve.SegmentCount==8):raise ValueError('Formula readback outline invalid')
            definition=profile['outer'] if wall is None else profile['inner'][str(wall)]
            maximum=0.;control_error=0.;knot_error=0.
            for q in range(4):
                segment=curve.SegmentCurve(2*q).ToNurbsCurve()
                if segment.Degree!=7 or len(segment.Points)!=len(definition['controls_mm']):raise ValueError('Formula readback degree differs')
                for i,p in enumerate(definition['controls_mm']):
                    expected=reproduced.rotate(p,q);actual=segment.Points[i]
                    control_error=max(control_error,math.hypot(actual.X/actual.W-expected[0],actual.Y/actual.W-expected[1]),abs(actual.W-definition['weights'][i]))
                for i,knot in enumerate(reproduced.expand_knots(definition)[1:-1]):knot_error=max(knot_error,abs(segment.Knots[i]-knot))
                for t in np.linspace(0,1,129):
                    p=segment.PointAt(float(t));xy=reproduced.rotate(reproduced.quarter(profile,wall)(float(t)),q)
                    maximum=max(maximum,math.hypot(p.X-xy[0],p.Y-xy[1]))
            if max(maximum,control_error,knot_error)>1e-10:raise ValueError('Formula 3DM readback differs')
            results[-3+index].update(rhino_readback_max_point_error_mm=maximum,
                                     rhino_control_error_mm=control_error,rhino_knot_error=knot_error)
    # All formal files are read only; this verifies the documentation did not replace them.
    checked=0
    for model in manifest['models']:
        for descriptor in model['files'].values():
            if digest(ROOT/descriptor['file'])!=descriptor['sha256']:raise ValueError('Formal CAD hash changed')
            checked+=1
    return {'passed':True,'formulas':results,'formal_cad_hashes_unchanged':checked,
            'formal_native_readbacks_repeated':False,
            'method':'Independent de Casteljau/de Boor versus SciPy, actual frozen OCCT BREP supports, and curve-only 3DM write/read definitions'}


def geometry(curve, t):
    import numpy as np
    v,a,j=[curve(t,nu=k) for k in (1,2,3)];speed=np.linalg.norm(v,axis=1)
    det=lambda x,y:x[:,0]*y[:,1]-x[:,1]*y[:,0]
    cross=det(v,a)
    return -cross/speed**3, -det(v,j)/speed**4+3*cross*np.sum(v*a,axis=1)/speed**6, speed


def figures(data,reports,candidates,temporary):
    import numpy as np
    from scipy.interpolate import BSpline
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import FancyArrowPatch,FancyBboxPatch
    font=Path('C:/Windows/Fonts/msyh.ttc')
    if font.exists():font_manager.fontManager.addfont(str(font))
    plt.rcParams.update({'font.family':'Microsoft YaHei' if font.exists() else 'DejaVu Sans',
                         'font.size':10,'axes.unicode_minus':False,'svg.fonttype':'path',
                         'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white'})
    out=DOC/'figures';out.mkdir(exist_ok=True)
    def finish(fig,name):
        fig.savefig(out/f'{name}.svg',bbox_inches='tight',metadata={'Date':None})
        fig.savefig(temporary/f'{name}.png',dpi=130,bbox_inches='tight');plt.close(fig)
    rep=load_reproducer();colors=['#225b95','#12876f','#c47525']
    fig,ax=plt.subplots(figsize=(12,3.0));ax.set(xlim=(0,12),ylim=(0,3));ax.axis('off')
    labels=[('原始 USDZ','变换与毫米单位\n侧壁截面和孔洞遮罩'),('约束拟合','候选公平比较\n冻结七次公共轮廓'),('参数化实体','法向内偏移与拉伸\n平板、锥面和切孔'),('规范数据和转换','BREP 支撑与修剪\n3DM · STP · X_T'),('原生验收与发布','定义、G3 和设计尺寸\n哈希绑定最终文件')]
    for i,(title,body) in enumerate(labels):
        x=.1+2.4*i
        ax.add_patch(FancyBboxPatch((x,.8),2.05,1.65,boxstyle='round,pad=0.07',facecolor='#eef4fa',edgecolor='#aec5db'))
        ax.text(x+1.025,2.08,title,ha='center',weight='bold',color='#174572',fontsize=11)
        ax.text(x+1.025,1.4,body,ha='center',va='center',linespacing=1.6,fontsize=9)
        if i<4:ax.add_patch(FancyArrowPatch((x+2.13,1.65),(x+2.34,1.65),arrowstyle='-|>',mutation_scale=12,color='#6384a2'))
    ax.text(6,.22,'拟合误差、设计尺寸和格式转换误差分别评价',ha='center',color='#536578')
    finish(fig,'pipeline')
    fig,axes=plt.subplots(1,2,figsize=(12,5.8),layout='constrained')
    for ax,(name,p) in zip(axes,data['profiles'].items()):
        for wall,color in zip((None,2,3),colors):
            pts=np.array(rep.sample(p,301,wall));ax.plot(pts[:,1],pts[:,2],color=color,label='外轮廓' if wall is None else f'{wall} mm 内轮廓',lw=1.5)
        cp=np.array(p['outer']['controls_mm']);ax.plot(cp[:,0],cp[:,1],'.--',color='#8f5064',ms=5,lw=.8,label='外角控制多边形')
        ax.scatter([cp[0,0],cp[-1,0]],[cp[0,1],cp[-1,1]],s=35,color='#8f5064')
        ax.set(title=f'{name}  公称 {p["nominal_width_mm"]:g} mm',aspect='equal',xlabel='X / mm',ylabel='Y / mm');ax.grid(alpha=.15);ax.legend(loc='center',fontsize=9)
    finish(fig,'profiles')
    fig,axes=plt.subplots(1,2,figsize=(12,5.7),layout='constrained')
    for ax,name in zip(axes,reports):
        file=ROOT/f'results/fitting/reference/{name}/section_0.50.csv';SOURCES[file.relative_to(ROOT).as_posix()]=digest(file)
        points=np.loadtxt(file,delimiter=',',skiprows=1);valid=points[:,2].astype(bool);r=reports[name];m=r['model']
        profile={'outer':{'controls_mm':m['controls_mm']}}
        xy=np.array(rep.sample(profile,301));ax.plot(xy[:,1],xy[:,2],color='#225b95',lw=1.4,label='选中拟合轮廓')
        ax.scatter(points[valid,0],points[valid,1],s=4,color='#179a81',label='有效观测')
        ax.scatter(points[~valid,0],points[~valid,1],s=9,color='#bc5a46',marker='x',label='排除的开口或补线')
        ax.set(title=f'{name}  源侧壁 50% 截面',xlabel='源平面 x / mm',ylabel='源平面 y / mm',aspect='equal');ax.grid(alpha=.15);ax.legend(loc='center',fontsize=9)
    finish(fig,'observations')
    fig,axes=plt.subplots(2,2,figsize=(12,7.2),layout='constrained')
    for col,(name,p) in enumerate(data['profiles'].items()):
        c=BSpline([0]*8+[1]*8,p['outer']['controls_mm'],7);t=np.linspace(0,1,2001)
        k,ks,speed=geometry(c,t);xy=c(t);arc=np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]
        for row,y,label in ((0,k,r'$\kappa\ (\mathrm{mm}^{-1})$'),(1,ks,r'$d\kappa/ds\ (\mathrm{mm}^{-2})$')):
            axes[row,col].plot(arc,y,color=colors[col],lw=1.7);axes[row,col].axhline(0,color='#9ba8b3',lw=.6)
            axes[row,col].set(xlabel='四分之一角段累计弧长 / mm',ylabel=label,title=name if row==0 else '')
            axes[row,col].grid(alpha=.15)
    finish(fig,'curvature')
    fig,axes=plt.subplots(1,2,figsize=(12,4.6),layout='constrained')
    for ax,(name,items) in zip(axes,candidates.items()):
        for item in items:
            rows=item['sections'];ax.plot([r['fraction']*100 for r in rows],[r['supported_corner']['rms_mm'] for r in rows],'.-',label=CANDIDATE_LABELS[item['name']],lw=1.3)
        ax.set(title=name+'  原始尺度有效角部',xlabel='源侧壁高度 / %',ylabel='RMS / mm');ax.grid(alpha=.15);ax.legend(fontsize=8)
    finish(fig,'fit_errors')
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    for ax,(name,p) in zip(axes,data['profiles'].items()):
        d=p['base'];k=d['cone_slope_dr_dz'];r=d['outer_cone_radius_intercept_mm'];zc=d['interface_z_mm'];height=d['height_mm'];offset=1.5*math.hypot(1,k)
        z=np.linspace(0,zc,80);zi=np.linspace(1.5,height,80)
        ax.plot(r+k*z,z,color='#225b95',lw=2,label='外锥面母线')
        ax.plot(r+k*zi-offset,zi,color='#12876f',lw=2,label='内锥面母线')
        ax.plot([r-3,r],[0,0],color='#225b95',lw=2);ax.plot([r-3,r+1.5*k-offset],[1.5,1.5],color='#12876f',lw=2)
        ax.plot([r+k*zc,r+k*zc+5],[zc,zc],color='#225b95',lw=2);ax.plot([r+k*height-offset,r+k*zc+5],[height,height],color='#12876f',lw=2)
        mid=zc/2;start=np.array([r+k*mid,mid]);end=start-1.5*np.array([1,-k])/math.hypot(1,k)
        ax.annotate('',xy=end,xytext=start,arrowprops={'arrowstyle':'<->','color':'#be7626'});ax.text(*(start+[.7,-.8]),'法向 1.5 mm',fontsize=9,color='#946022')
        ax.set(title=f'{name}  母线与水平面 {d["cone_angle_to_horizontal_degrees"]:g}°',xlabel='半径 r / mm',ylabel='Z / mm',aspect='equal');ax.grid(alpha=.15);ax.legend(fontsize=8,loc='upper left')
    finish(fig,'base_sections')
    from enclosure.rear_profile import RearProfile
    fig,axes=plt.subplots(1,2,figsize=(12,4.7),layout='constrained')
    ax=axes[0]
    for j in range(5):
        s=(np.arange(8-j%2)-(7-j%2)/2)*2;z=np.full(len(s),j*math.sqrt(3));ax.scatter(s,z,s=65,facecolors='#dbeaf8',edgecolors='#225b95')
    ax.plot([-1,1,0,-1],[0,0,math.sqrt(3),0],color='#c47525',lw=1.8)
    ax.set(title='先在平面布置孔心  局部示意',xlabel='展开弧长坐标 s / mm',ylabel='相对高度 z / mm',aspect='equal');ax.grid(alpha=.15)
    p=data['profiles']['mac-studio'];rp=RearProfile(p['outer']['controls_mm']);s=np.linspace(37,85,1001);xy,tangent=rp.evaluate(s)
    ax=axes[1];ax.plot(xy[:,0],xy[:,1],color='#225b95',lw=1.6)
    centers,tangent=rp.evaluate(np.arange(40,85,8));normal=np.c_[-tangent[:,1],tangent[:,0]]
    ax.scatter(centers[:,0],centers[:,1],s=22,color='#225b95');ax.quiver(centers[:,0],centers[:,1],normal[:,0]*10,normal[:,1]*10,angles='xy',scale_units='xy',scale=1,color='#c47525',width=.005)
    ax.set(title='右侧圆角局部  孔心贴合与内法线',xlabel='X / mm',ylabel='Y / mm',aspect='equal',xlim=(35,90),ylim=(-103,-77));ax.grid(alpha=.15)
    ax.text(37,-80,'俯视图；箭头仅表示钻孔方向',fontsize=9,color='#946022')
    finish(fig,'hole_mapping')


def write_tables(data,manifest,reports,candidates,heights,parameters,audits,offsets,proof):
    block('README.md','SUMMARY',f'文档数据绑定发布 `{manifest["release"]}`，包含外轮廓公式、四种内轮廓与独立 3DM 曲线复现检查，以及正式 CAD 文件的 SHA-256 核对。')
    block('01_PROJECT.md','DIMENSIONS',table(['机型','外宽 mm','壳体高 mm','底座高 mm','嵌入 mm','装配高 mm','底座锥角'],[
        ['Mini','127','43','8','1.5','49.5','45°'],['Studio','197','86.5','10.0','1.5','95.0','30°']]))
    candidate_rows=[];fit_rows=[];height_rows=[]
    for name,r in reports.items():
        for item in candidates[name]:
            candidate_rows.append([name,CANDIDATE_LABELS[item['name']]+('（选中）' if item['name']==r['selected_model'] else ''),str(item['degree']),len(item['controls_mm']),
                                   f'{item["validation"]["rms_mm"]:.9f}',f'{item["validation"]["max_mm"]:.9f}',f'{item["test"]["rms_mm"]:.9f}'])
        for role,label in (('train','训练'),('validation','验证'),('test','测试')):
            metric=r['model'][role];scale=r['nominal_xy_scale'];count=sum(x['supported_corner']['count'] for x in r['model']['sections'] if x['role']==role)
            fit_rows.append([name,label,count,f'{metric["rms_mm"]:.9f}',f'{metric["max_mm"]:.9f}',f'{scale*metric["rms_mm"]:.9f}',f'{scale*metric["max_mm"]:.9f}'])
        fields=heights[name]['candidate_fields'];baseline=fields[0]['roles']['validation']['rms_mm']
        for item in fields:
            validation=item['roles']['validation'];height_rows.append([name,item['height_degree'],f'{validation["rms_mm"]:.9f}',f'{validation["max_mm"]:.9f}',f'{baseline-validation["rms_mm"]:.9f}'])
    block('02_FITTING.md','CANDIDATES',table(['机型','候选','次数','控制点数','验证 RMS mm','验证最大 mm','测试 RMS mm'],candidate_rows))
    block('02_FITTING.md','FIT_RESULTS',table(['机型','分组','有效角部点数','原始 RMS mm','原始最大 mm','公称 RMS mm','公称最大 mm'],fit_rows))
    block('02_FITTING.md','HEIGHT_RESULTS',table(['机型','高度变化次数','验证 RMS mm','验证最大 mm','RMS 改善 mm'],height_rows))
    block('02_FITTING.md','G3_RESULTS',table(['机型','公称最小曲率半径 mm','原始最小参数速度','端点曲率','端点曲率变化率','前半段单调检查'],[
        [name,f'{r["g3"]["minimum_radius_mm"]*r["nominal_xy_scale"]:.12g}',f'{r["g3"]["minimum_speed"]:.12g}','0','0','密采样通过'] for name,r in reports.items()]))
    controls=[]
    for name,p in data['profiles'].items():
        controls.append(f'### {name} 外角段控制点\n\n'+table(['i','X mm','Y mm'],[[i,repr(v[0]),repr(v[1])] for i,v in enumerate(p['outer']['controls_mm'])]))
        controls.append(f'原始拟合宽度 {reports[name]["design_width_mm"]!r} mm；公称统一比例 {p["nominal_xy_scale"]!r}。')
    block('03_MATHEMATICS.md','CONTROLS','\n\n'.join(controls))
    reproduced=load_reproducer();points=[];point_table=[]
    for name,profile in data['profiles'].items():
        for wall in (None,2,3):
            for t in (0.,.25,.5,.75,1.):
                xy=reproduced.quarter(profile,wall)(t);label='outer' if wall is None else f'inner_{wall}mm'
                points.append([name,label,t,*xy])
                if wall is None:point_table.append([name,repr(t),repr(xy[0]),repr(xy[1])])
    import csv
    with (DOC/'reference_points.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream);writer.writerow(['model','curve','t','x_mm','y_mm']);writer.writerows(points)
    block('03_MATHEMATICS.md','CHECK_POINTS',table(['机型','t','X mm','Y mm'],point_table)+'\n\n完整 30 个核对点见 [reference_points.csv](reference_points.csv)，包含外轮廓及两种内轮廓。')
    block('03_MATHEMATICS.md','OFFSET_RESULTS',table(['机型','壁厚 mm','法向偏移最大差 mm','最近距离最大差 mm','最小 1−dκ'],[
        [name,t,f'{o["normal_offset_max_error_mm"]:.12g}',f'{o["nearest_outer_distance_max_error_mm"]:.12g}',f'{o["minimum_one_minus_thickness_times_curvature"]:.12g}'] for (name,t),o in offsets.items()]))
    block('03_MATHEMATICS.md','MINI_PHASE',f'当前相位为 `{data["mini_vents"]["phase_radians"]!r}` rad，角间距为 `{data["mini_vents"]["angular_pitch_radians"]!r}` rad。')
    inner=['# 完整内曲线控制表','此表直接取自当前冻结公称实体的第一象限内侧挤出支撑。次数均为 7，权重均为 1，参数区间 [0,1]。所有 39 个控制点按原顺序列出。完整节点向量为八个 0、1/32 至 31/32、八个 1。机器可读版本见 [完整参数](geometry_definition.json)。']
    for name,p in data['profiles'].items():
        for wall,d in p['inner'].items():inner.extend([f'## {name} 内偏移 {wall} mm',table(['i','X mm','Y mm'],[[i,repr(v[0]),repr(v[1])] for i,v in enumerate(d['controls_mm'])])])
    (DOC/'05_INNER_CONTROLS.md').write_text('\n\n'.join(inner)+'\n',encoding='utf-8')
    block('04_REPRODUCTION.md','REPRODUCTION_RESULTS',table(['机型','曲线','对 SciPy 最大坐标差 mm','对实际 BREP 最大点差 mm','3DM 回读最大点差 mm'],[
        [r['model'],r['curve'],f'{r["scipy_max_coordinate_error_mm"]:.3e}',f'{r["actual_brep_max_point_error_mm"]:.3e}',f'{r["rhino_readback_max_point_error_mm"]:.3e}'] for r in proof['formulas']])+f'\n\n共核对 {proof["formal_cad_hashes_unchanged"]} 个正式 CAD 文件，哈希全部保持原值。')
    rows=[]
    for (name,t),records in audits.items():
        base=records['base'];feature=records['features']
        rows.append([name,t,'通过' if base['passed'] and feature['passed'] else '失败',f'{base["measured_cone_angle_to_horizontal_degrees"]:.12g}',
                     f'{base["measured_conical_normal_thickness_mm"]:.12g}',', '.join(f'{v:.12g}' for v in base['measured_vent_clearances_along_cone_mm'])])
    studio=audits['mac-studio',2]['features']
    text='20 个模型、60 个使用文件、20 个母版和 8 项设计审计均具有当前通过记录。\n\n'
    text+=table(['机型','壳体厚度 mm','设计审计','实测锥角 °','实测锥壁厚 mm','外孔口两端沿面边距 mm'],rows)
    text+=f'\n\nStudio 每圈孔心的最大高度范围为 {studio["horizontal_base_rings"]["maximum_ring_height_range_mm"]:.3e} mm；'
    text+=f'背孔独立回算弧长最大差为 {studio["wrapped_rear_grid"]["maximum_recovered_arc_error_mm"]:.3e} mm。全部背孔实测解析圆柱半径误差为 {studio["rear_hole_geometry"]["maximum_radius_error_mm"]!r} mm。'
    block('04_REPRODUCTION.md','ACCEPTANCE',text)


def render_html():
    import mistune
    import matplotlib
    from matplotlib.mathtext import math_to_image
    from matplotlib.font_manager import FontProperties
    parser=mistune.create_markdown(escape=False,plugins=['table'])
    equation_count=0
    def formula(text,inline=False):
        nonlocal equation_count
        equation_count+=1;text=text.strip();stream=io.StringIO()
        # A display-ending period is normal prose punctuation, not part of the equation.
        with matplotlib.rc_context({'savefig.transparent':True}):
            math_to_image('$'+text+'$',stream,prop=FontProperties(size=12 if inline else 15),format='svg',color='#163d60')
        svg=stream.getvalue();svg=svg[svg.index('<svg'):]
        prefix=f'eq{equation_count}_'
        svg=re.sub(r'\bid="([^"]+)"',lambda m:f'id="{prefix}{m.group(1)}"',svg)
        svg=re.sub(r'((?:xlink:)?href="#)([^"]+)(")',lambda m:m.group(1)+prefix+m.group(2)+m.group(3),svg)
        svg=re.sub(r'url\(#([^\)]+)\)',lambda m:'url(#'+prefix+m.group(1)+')',svg)
        tag='span' if inline else 'div';klass='inline-math' if inline else 'display-math'
        return f'<{tag} class="{klass}" aria-label="{html.escape(text,quote=True)}">{svg}</{tag}>'
    chapters=[];navigation=[]
    for number,name in enumerate(CHAPTERS,1):
        text=(DOC/name).read_text(encoding='utf-8');title=text.splitlines()[0].removeprefix('# ')
        placeholders={}
        def hold(m,inline):
            key=f'DOCMATHPLACEHOLDER{len(placeholders)}END';placeholders[key]=formula(m.group(1),inline);return key
        text=re.sub(r'\$\$(.*?)\$\$',lambda m:hold(m,False),text,flags=re.S)
        text=re.sub(r'(?<!\$)\$([^\n$]+)\$(?!\$)',lambda m:hold(m,True),text)
        output=parser(text)
        for key,value in placeholders.items():output=output.replace('<p>'+key+'</p>',value).replace(key,value)
        for figure in sorted((DOC/'figures').glob('*.svg')):
            output=output.replace('src="figures/'+figure.name+'"','src="data:image/svg+xml;base64,'+base64.b64encode(figure.read_bytes()).decode()+'"')
        for i,chapter in enumerate(CHAPTERS,1):output=output.replace(f'href="{chapter}"',f'href="#chapter-{i}"')
        output=re.sub(r'<h([23])>(.*?)</h\1>',lambda m:f'<h{m.group(1)} id="c{number}-{hashlib.sha256(m.group(2).encode()).hexdigest()[:9]}">{m.group(2)}</h{m.group(1)}>',output)
        chapters.append(f'<section id="chapter-{number}">{output}</section>')
        navigation.append(f'<a href="#chapter-{number}">{number:02d} {html.escape(title)}</a>')
    style='''
    :root{color-scheme:light;--ink:#233345;--blue:#194c79;--line:#d9e3ec}
    *{box-sizing:border-box}body{margin:0;color:var(--ink);background:#f3f6f9;font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif;font-size:16px;line-height:1.8}
    aside{position:fixed;inset:0 auto 0 0;width:245px;background:#143855;color:white;padding:32px 20px;overflow:auto}aside strong{display:block;font-size:20px;line-height:1.5;margin-bottom:22px}aside a{display:block;color:#d9e9f5;text-decoration:none;margin:14px 0;font-size:14px}
    main{margin-left:245px;max-width:1220px;padding:32px 42px 60px}header,section{background:white;border:1px solid var(--line);border-radius:10px;padding:30px 34px;margin-bottom:28px;box-shadow:0 4px 20px #1c3e5d06}
    h1{font-size:29px;color:var(--blue);line-height:1.35;margin:0 0 24px}h2{font-size:22px;color:var(--blue);margin-top:38px;border-bottom:1px solid var(--line);padding-bottom:8px}h3{font-size:18px;margin-top:28px;color:#375974}
    a{color:#21649c;overflow-wrap:anywhere}p{margin:16px 0}table{border-collapse:collapse;display:block;overflow-x:auto;font-size:13px;margin:20px 0;line-height:1.6}th,td{border:1px solid var(--line);padding:9px 11px;text-align:left;vertical-align:top;white-space:normal}th{background:#edf4fa;font-weight:600}tr:nth-child(even){background:#f9fbfd}
    img{max-width:100%;height:auto;display:block;margin:24px auto}code{font-family:Consolas,monospace;background:#f0f4f7;border-radius:3px;padding:2px 4px;font-size:.88em;overflow-wrap:anywhere}pre{background:#142f43;color:#e4eef5;border-radius:7px;padding:18px;overflow:auto;font-size:14px;line-height:1.55}pre code{padding:0;background:none;overflow-wrap:normal}
    .display-math{overflow-x:auto;padding:15px 12px;border-left:3px solid #91b2d0;background:#f7fafc;margin:22px 0}.display-math svg{display:block;max-width:none}.inline-math{display:inline-block;vertical-align:middle;line-height:1}.inline-math svg{display:block;max-height:1.65em;width:auto}li{margin:8px 0}header p{color:#50697f}.eyebrow{font-size:13px;letter-spacing:1px;color:#6b8498}
    @media(max-width:1050px){aside{position:static;width:auto;padding:18px 24px}aside a{display:inline-block;margin:5px 18px 5px 0}aside strong{margin:0 0 10px}main{margin-left:0;padding:20px}header,section{padding:24px}}
    @media print{aside{display:none}main{margin:0;padding:0;max-width:none}body{background:white;font-size:10pt}header,section{box-shadow:none;border:0;padding:0;break-before:page}h1{font-size:21pt}h2{font-size:15pt;break-after:avoid}table{display:table;font-size:8pt}tr{break-inside:avoid}img{max-height:210mm}.display-math svg{max-width:100%;height:auto}pre{white-space:pre-wrap;background:#f0f4f7;color:#142f43}}
    '''
    document='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mac Mini Mac Studio 项目技术文档</title><style>'+style+'</style></head><body>'
    document+='<aside><strong>Mac Mini<br>Mac Studio<br>项目技术文档</strong>'+''.join(navigation)+'<a href="geometry_definition.json">完整精度参数 JSON</a><a href="reproduce_profiles.py">独立复现脚本</a><a href="../../DELIVERY.md">正式文件索引</a></aside>'
    document+='<main><header><div class="eyebrow">工程方案 · 数学定义 · 可复现数据</div><h1>从源网格到同一条 G3 曲线</h1><p>说明项目运行流程、拟合方法与误差、三维建模方案，以及如何用完整参数重画相同轮廓。公式与图表已嵌入本页，可离线阅读。</p><p>SVG 和 CSV 是采样显示；精确曲线由次数、控制点、权重、节点及连接顺序定义。</p></header>'+''.join(chapters)+'</main></body></html>'
    (DOC/'index.html').write_text(document,encoding='utf-8')
    return {'equations_rendered':equation_count,'chapters':len(CHAPTERS),'offline':True}


def links_check(pending_report=False):
    from urllib.parse import unquote
    checked=0;errors=[]
    for file in sorted(DOC.glob('*.md')):
        text=file.read_text(encoding='utf-8')
        text=re.sub(r'\$\$(.*?)\$\$','',text,flags=re.S)
        text=re.sub(r'(?<!\$)\$([^\n$]+)\$(?!\$)','',text)
        for match in re.finditer(r'!?\[[^\]]*\]\(([^)]+)\)',text):
            target=match.group(1).split('#')[0].strip('<>')
            if not target or '://' in target:continue
            resolved=(file.parent/unquote(target)).resolve()
            if not resolved.exists() and not (pending_report and resolved==ROOT/'validation/documentation.json'):
                errors.append(f'{file.name}: {target}')
            checked+=1
    if errors:raise ValueError(errors)
    return checked


def check():
    report=json.loads((ROOT/'validation/documentation.json').read_text(encoding='utf-8'))
    errors=[]
    for descriptor in report['sources']+report['outputs']:
        path=ROOT/descriptor['file']
        if not path.is_file() or digest(path)!=descriptor['sha256']:errors.append(descriptor['file'])
    if errors:raise ValueError('Stale documentation bindings: '+str(errors))
    print(json.dumps({'passed':True,'source_files':len(report['sources']),'output_files':len(report['outputs']),
                      'local_links':links_check(),'formal_CAD_modified':False},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.check:check();return
    temporary=ROOT/'.tmp/documentation-preview'
    print('Collect exact definitions from the accepted release',flush=True)
    data,manifest,reports,candidates,heights,parameters,audits,offsets=collect_data()
    print('Verify independent formulas against actual supports and curve 3DM readback',flush=True)
    proof=verify_formulas(data,manifest,temporary)
    print('Generate source-derived figures and complete parameter tables',flush=True)
    figures(data,reports,candidates,temporary)
    write_tables(data,manifest,reports,candidates,heights,parameters,audits,offsets,proof)
    print('Render the offline mathematical manual',flush=True)
    rendered=render_html();links=links_check(pending_report=True)
    source_code=['macfit/fitting.py','macfit/geometry.py','macfit/pipeline.py','macfit/verification.py',
                 'macfit/io.py','macfit/height.py','enclosure/wall_offset.py','enclosure/rear_profile.py',
                 'enclosure/studio_rear_pattern.py','enclosure/studio_base_pattern.py','enclosure/mini_capsules.py',
                 'enclosure/current_design.py','tools/exact_verify.py','tools/exact_publish.py','project.py',
                 'tools/build_technical_docs.py','docs/technical/reproduce_profiles.py','requirements-dev.txt']
    for name in source_code:SOURCES[name]=digest(ROOT/name)
    outputs=[p for p in DOC.rglob('*') if p.is_file()]
    result={'schema':'technical-documentation-verification-v1','passed':True,
            'generated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'release':manifest['release'],
            'formula_verification':proof,'rendering':rendered,'local_links_checked':links,
            'sources':[{'file':p,'sha256':h} for p,h in sorted(SOURCES.items())],
            'outputs':[{'file':p.relative_to(ROOT).as_posix(),'sha256':digest(p)} for p in sorted(outputs)],
            'preview_directory':'.tmp/documentation-preview','visual_review':'pending'}
    save(ROOT/'validation/documentation.json',result)
    print(json.dumps({'passed':True,'release':manifest['release'],'formulas_checked':len(proof['formulas']),**rendered,'local_links':links},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
